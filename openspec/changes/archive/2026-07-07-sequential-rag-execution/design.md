## Context

The backend's `execute_rag_query()` in `_executor.py` currently dispatches all selected RAG backends concurrently via `asyncio.gather()`. In practice, this concurrency provides no wall-clock benefit because all 3 backends share a single MLXLLM singleton whose `_generate_lock` serializes GPU inference. Total time ≈ sum of 3 generations (~240s) — the same as sequential.

However, the parallel structure introduces significant complexity:
- Frontend needs progressive rendering to show partial results
- Fragment-based polling must handle out-of-order completions
- Lock contention between backends must be managed
- Fast answers can disappear when timeout guard fires (the disappearing-answer bug)

The sequential model eliminates this complexity while keeping identical total wall time.

### Current architecture

```
execute_rag_query()
  │
  ├── asyncio.gather(          ← all 3 start concurrently
  │     _execute_cosine(),
  │     _execute_llamaindex(),
  │     _execute_langchain()
  │   )
  │
  └── Each backend:
        ├── retrieval (no lock)
        ├── generate (acquires _generate_lock)
        └── store result in TaskManager
```

### Proposed architecture

```
execute_rag_query()
  │
  ├── _execute_cosine()        ← runs first
  │     ├── retrieval
  │     ├── generate (acquires _generate_lock)
  │     └── store result
  │
  ├── _execute_llamaindex()    ← runs second
  │     ├── retrieval
  │     ├── generate (acquires _generate_lock)
  │     └── store result
  │
  └── _execute_langchain()     ← runs third
        ├── retrieval
        ├── generate (acquires _generate_lock)
        └── store result
```

## Goals / Non-Goals

**Goals:**
- Change backend execution from parallel (`asyncio.gather()`) to sequential (ordered loop)
- Eliminate the GPU lock contention scenario in multi-backend queries
- Simplify frontend fragment polling (results arrive in predictable order)
- Fix the disappearing-answer bug as a natural consequence (each result is rendered before the next starts)
- Keep same total wall-clock time for multi-backend queries

**Non-Goals:**
- Changing the `_generate_lock` in `MLXLLM` — it stays for other concurrent use cases
- Changing the backend API contract (`/query/start`, `/query/status`)
- Changing individual backend implementations (cosine, LlamaIndex, LangChain chains)
- Reducing per-backend latency (individual backend speed is unchanged)
- Changing backend selection logic or ordering

## Decisions

### Decision 1: Sequential execution via simple for loop

**Selected: Replace `asyncio.gather()` with `for` loop**

```python
# Before
tasks = [run_backend(b) for b in backends_to_run]
await asyncio.gather(*tasks)

# After
for b in backends_to_run:
    await run_backend(b)
```

- 👍 Simplest possible change — 2 lines become 2 lines
- 👍 Each backend runs to completion before the next starts
- 👍 Each backend's result is stored before the next begins
- 👍 `_generate_lock` is never contended during multi-backend queries
- 👎 Total wall time is identical (sum of all three, same as before)
- 👎 Last backend's result appears later for the user (but same as before in practice)

**Alternative considered**: `asyncio.as_completed()` — runs all tasks but yields results as they complete. More complex with no benefit since lock serialization means tasks complete in order anyway.

### Decision 2: Backend execution order

**Selected: Keep existing order from `request.backends` (typically [cosine, llamaindex, langchain])**

The order is already defined by the frontend's backend selection. No ordering change needed. Each backend runs in the order the user selected them.

- 👍 Predictable — first backend's result appears first
- 👍 Fastest backends (cosine, LlamaIndex) appear before LangChain
- 👍 No configuration needed

### Decision 3: Frontend fragment simplification

**Selected: Keep fragment polling but simplify**

With sequential execution:
- Results arrive in order (no out-of-order complexity)
- Each result is stored before the next backend starts
- Fragment polls, sees new results one at a time in order
- No need for the complex `rendered_backends` dedup across parallel backends
- Fragment still stores results in `st.session_state.messages` and calls `st.rerun()`
- Timeout guard: each backend runs individually, so the 120s timeout is less likely to fire. However, keep it as a safety net.

**Alternative considered**: Remove fragment entirely and use synchronous rendering. Rejected because backends still take ~80s each — blocking the UI for 240s is unacceptable. Polling is still the right approach.

### Decision 4: Timeout guard

**Selected: Keep 120s timeout, adjusted per-backend**

With sequential execution, the total wall time can still reach 240s (3 × 80s). However, the timeout guard currently checks total elapsed time since query start. For the first backend, this is fine (~80s < 120s). For the third backend (LangChain), it may be ~160s elapsed before LangChain even starts retrieving.

**Adjustment**: Change the timeout check to fire when any single backend runs for >120s, rather than total elapsed time. This gives each backend a full 120s window regardless of where it falls in the sequence.

Alternatively, keep the existing total-time check and extend to 300s (to cover 3 × 100s worst case). This is simpler and still provides a safety net.

**Selected**: Keep total-time timeout at 300s. The 120s per-backend approach adds complexity. A 300s ceiling provides a safety net without false positives.

## Architecture

### Before (parallel dispatch)

```
Frontend                          Backend
───────────────────────────────────────────────────────
POST /query/start ──────────────▶ execute_rag_query()
                                    │
  Poll /query/status ◀──────────────┤ asyncio.gather(
  (unpredictable order)             │   cosine()      ← ~80s
                                    │   llamaindex()  ← ~80s (queued on lock)
                                    │   langchain()   ← ~80s (queued on lock)
                                    │ )
                                    │ Total: ~240s
```

### After (sequential dispatch)

```
Frontend                          Backend
───────────────────────────────────────────────────────
POST /query/start ──────────────▶ execute_rag_query()
                                    │
  Poll /query/status ◀──────────────┤ for b in backends:
  (predictable order)               │   await backend(b)
  cosine @ ~80s  ───────────────────┤   cosine()      ← ~80s
  llamaindex @ ~160s ───────────────┤   llamaindex()  ← ~80s
  langchain @ ~240s ────────────────┤   langchain()   ← ~80s
                                    │ Total: ~240s
```

## Risks / Trade-offs

| Risk | Severity | Mitigation |
|------|----------|------------|
| Total wall time same as before | Low | Sequential doesn't add time — parallel wasn't saving any due to lock serialization. This is acknowledged, not a regression. |
| Third backend (LangChain) now starts much later | Medium | LangChain already started last under parallel due to lock contention. This is no worse — LangChain was already waiting ~160s for the lock before it could generate. |
| One backend hangs, blocking all subsequent backends | Medium | Keep the 300s total-time timeout guard. Each backend also has individual timeout (LangChain 240s via existing change, cosine/LlamaIndex have implicit timeouts). |
| Frontend sees long gaps between results | Low | Each backend takes ~80s. User sees result 1 at ~80s, result 2 at ~160s, result 3 at ~240s. Under parallel, they saw result 1 at ~80s then result 2 and 3 much later — so the perceived experience is similar. |
| `_generate_lock` preheating benefit lost | Low | Under parallel, the first backend to acquire the lock "warms up" the GPU for subsequent backends. Under sequential, each backend still acquires the lock for its generation, so preheating still occurs. |
