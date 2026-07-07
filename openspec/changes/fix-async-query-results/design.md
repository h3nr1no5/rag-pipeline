## Context

The multi-backend RAG query system allows users to select any combination of 3 backends (cosine similarity, LlamaIndex, LangChain). Queries execute via an async background task (`TaskManager` + `execute_rag_query` using `asyncio.gather()`). The frontend polls `/query/status/{id}` every 1 second via a Streamlit `@fragment(run_every=1.0)`, progressively rendering completed results inline.

**Current problems working together to create the bug:**

1. **Lock serialization**: The `MLXLLM` singleton has a module-level `_generate_lock = asyncio.Lock()`. In the async executor flow (`_executor.py`), each backend calls the LLM's `generate()` which acquires this lock. Since `asyncio.gather()` gives all 3 backends a fair chance but the lock serializes the LLM call, total wall time ≈ sum of individual generation times (roughly 80s × 3 = 240s).

2. **Missing backend timeout**: `_execute_langchain_backend()` has no timeout wrapping, unlike the synchronous LangChain route which has a 160s timeout.

3. **Fragment output volatility**: The `@fragment(run_every=1.0)` renders `st.chat_message()` and `st.expander()` elements inline. Each fragment rerun **replaces all previous fragment output**. The fragment's 120s timeout guard renders `st.error()` and returns without `st.rerun()`, which means the accumulated answers (cosine, LlamaIndex) that were rendered by the fragment in previous runs are replaced by the error. The main message loop never re-renders them because no full page rerun is triggered.

4. **No test-mode timeout override**: The 120s frontend timeout is hardcoded, making E2E testing of timeout behavior prohibitive (requires 2+ minute wait per test).

## Goals / Non-Goals

**Goals:**
- Fast answers (cosine, LlamaIndex) remain visible even when LangChain is still running or times out
- LangChain execution has a bounded maximum time (backend timeout)
- GPU lock contention is minimized — retrieval phases of different backends can overlap
- Fragment rendering is stable — results don't disappear on subsequent reruns
- Timeout behavior is testable via environment variable override

**Non-Goals:**
- Changing the LLM singleton pattern or lazy-loading mechanism
- Introducing a dedicated task queue or Celery/RQ
- Changing the backend API contract (`/query/start`, `/query/status`)
- Switching to WebSockets or SSE for push-based updates
- Parallel LLM inference (MLX doesn't support concurrent GPU access from multiple coroutines)

## Decisions

### Decision 1: Fragment rendering strategy — "render via main loop only"

**Option A (selected): Fragment polls, stores results, triggers `st.rerun()`**
The fragment's only job is to poll, store results in `st.session_state`, and call `st.rerun()` when new results arrive or state changes. The main message loop handles ALL rendering via `render_message()`. The fragment produces no direct visible output (no `st.chat_message`, `st.markdown`, etc.).

- 👍 Clean separation of concerns: polling ≠ rendering
- 👍 Main loop rendering is stable — not replaced on fragment reruns
- 👍 Results persist across fragment reruns naturally
- 👎 Every new result triggers a full page rerun (potential flicker)
- 👎 More `st.session_state` plumbing for tracking what's new vs. already rendered

**CRITICAL**: Without a short-circuit guard, every fragment poll cycle would call `st.rerun()` even when no new results exist, causing an infinite rerun loop. The short-circuit (check `rendered_backends` size vs results) is **mandatory**, not optional.

**Option B (current, rejected): Fragment polls and renders inline**
The fragment both polls and renders. This causes the disappearing answer bug.

**Option C (rejected): Two fragments — one for polling, one for rendering**
Unnecessarily complex. A single fragment that stores results + `st.rerun()` achieves the same effect.

### Decision 2: Timeout guard behavior

**Selected: `st.rerun()` before error return**

```python
if timeout_condition:
    st.error("⏰ Query timed out...")
    st.session_state.task_started = False
    st.rerun()  # <-- added: main loop renders accumulated results
    return
```

The `st.rerun()` ensures the main message loop runs once more, picking up any results stored in `st.session_state.messages` from earlier fragment runs. These results then persist in the DOM regardless of what the fragment does next.

The `return` after `st.rerun()` is technically unreachable (the rerun exception aborts the fragment), but is kept for defensive clarity and to match existing code patterns.

**Rationale**: This is the minimal change that fully fixes the disappearing-answer bug. Without `st.rerun()`, the main loop never sees the accumulated results.

### Decision 3: Backend timeout for LangChain

**Selected: `asyncio.wait_for()` at 240 seconds**

```python
LANGCHAIN_TIMEOUT = 240  # configurable via settings

async def _execute_langchain_backend(...):
    try:
        response_text, retrieved = await asyncio.wait_for(
            qa_chain.generate(query, ...),
            timeout=LANGCHAIN_TIMEOUT
        )
    except asyncio.TimeoutError:
        return {"error": "LangChain backend timed out"}
```

**Rationale for 240s**: With GPU lock contention, LangChain is last in line. Approximate breakdown: 2 prior generations × ~80s + self generation ~80s = ~240s. A 240s timeout allows LangChain to complete under worst-case lock contention.

**Configurability**: The `LANGCHAIN_TIMEOUT` constant should be defined in `_executor.py` (or `src/core/config.py`) so it can be adjusted per-deployment and overridden in tests. The backend already has `_GENERATE_LOCK_TIMEOUT = 300` — LangChain timeout should be lower since it's a frontend-facing ceiling, not a hardware guard.

**Alternative considered**: 300s (matches lock timeout but extends user wait unnecessarily). 180s (too tight, may fail under lock contention on slower hardware).

### Decision 4: Lock scope — confirmed correct, no restructuring needed

**Selected: Keep existing `_generate_lock` scope — add trace logging only**

Investigation confirmed that all 3 backends already separate retrieval from LLM generation:

- **LangChain** (`chain_langchain.py`): Line 265 calls `self._retriever.retrieve(question)` — no lock held. Line 289 calls `llm.generate(prompt)` — lock acquired inside `MLXLLM.generate()`.
- **Cosine similarity** (`chain_cosine.py`): Retrieval (embedding similarity search) runs first. `generate()` called last with lock scoped inside.
- **LlamaIndex** (`chain_llamaindex.py`): Same pattern — retrieval first, generation last with lock.

Since `asyncio.gather()` runs all 3 coroutines concurrently, each one independently acquires the lock only when entering the LLM `generate()` call. Retrieval phases of different backends CAN overlap. **No code changes needed in llm.py or any backend chain.**

Add trace-level logging (via `logging.Logger.trace` or `debug`) at lock acquire/release points to verify timing in production.

**Risk**: The `_generate_lock` is module-level in `llm.py` with a 300s acquire timeout. A backend that acquires the lock and then crashes while holding it would block other backends until the 300s timeout. This is a pre-existing risk, not introduced by this change.

### Decision 5: Test-mode timeout override

**Selected: `FRONTEND_QUERY_TIMEOUT` environment variable**

```python
# In Chat.py or a shared config location
_FRONTEND_QUERY_TIMEOUT = int(os.environ.get("FRONTEND_QUERY_TIMEOUT", "120"))
```

The hardcoded `120` in the timeout guard becomes an env-var-backed constant. In production, default is 120s. In tests, set `FRONTEND_QUERY_TIMEOUT=5` to allow E2E verification of timeout behavior in seconds instead of minutes.

**Rationale**: Without this override, the only way to test timeout behavior is with a 120+ second wait, which is impractical for CI. This is a common pattern (similar to `TEST_DATABASE_URL`).

**Alternative considered**: Test-only config override via `st.session_state` — too fragile, doesn't work for integration tests that bypass Streamlit.

### Decision 6: `render_message()` expander label

**Selected: Update label from static to dynamic**

```python
# Before (chat_message.py):
with st.expander("📚 Sources"):

# After:
source_count = len(content.get("sources", []))
with st.expander(f"📚 Sources ({source_count})"):
```

This matches the dynamic label the fragment was rendering (`f"📚 Sources ({len(sources)})"`) and prevents visual regression when the fragment is refactored to stop inline rendering.

## Architecture

### Before (current flow)

```
Frontend                         Backend
────────                         ────────
@fragment(run_every=1.0)
  │                                  │
  │  POST /query/start ──────────────▶  execute_rag_query()
  │                                  │    asyncio.gather(
  │  ┌───────────────────────────────┤      _execute_cosine()    ← lock held
  │  │ Poll /query/status ───────────┤      _execute_llamaindex() ← lock held
  │  │   → renders st.chat_message() │      _execute_langchain() ← lock held
  │  │   → renders st.expander()     │    )
  │  │   (VOLATILE: replaced each     │
  │  │    fragment rerun)            │
  │  │                               │
  │  │ At 120s: timeout guard        │
  │  │ → st.error() (replaces all)   │
  │  │ → return (no st.rerun())      │
  │  └───────────────────────────────┘
  │
Main message loop (stable)
  → renders st.session_state.messages
  → NEVER runs after timeout (no st.rerun())
  → Results stored in state but never rendered
```

### After (fixed flow)

```
Frontend                         Backend
────────                         ────────
@fragment(run_every=1.0)
  │                                  │
  │  POST /query/start ──────────────▶  execute_rag_query()
  │                                  │    asyncio.gather(
  │  ┌───────────────────────────────┤      _execute_cosine()
  │  │ Poll /query/status            │        → retrieve (no lock)
  │  │   → store results in state    │        → generate (lock held)
  │  │   → st.rerun() if new         │      _execute_llamaindex()
  │  │   → return early if none      │        → retrieve (no lock)
  │  │                               │        → generate (lock held)
  │  │ At 120s:                      │      _execute_langchain()
  │  │ → st.error()                  │        → retrieve (no lock)
  │  │ → st.rerun()                  │        → generate (lock held, 240s timeout)
  │  │ → return                      │    )
  │  └───────────────────────────────┘
  │
Main message loop (rerun triggered)
  → renders st.session_state.messages
  → shows all accumulated results + timeout error
  → results persist in DOM
```

## Risks / Trade-offs

| Risk | Severity | Mitigation |
|------|----------|------------|
| `st.rerun()` in fragment causes visual flicker | Low | Streamlit reruns are fast (no network); the main loop's output is stable |
| Fragment short-circuit is not implemented — infinite rerun loop | **High** | This is a mandatory requirement (Decision 1). Task marked as must-implement, not optional. |
| LangChain 240s timeout too tight under memory pressure | Low | Configurable — can be bumped per-deployment. Also, lock investigation confirms retrieval overlaps, so actual LangChain time is ~80s not 240s. |
| Lock is held for entire generation — crash while holding lock blocks others | Low | Pre-existing risk. 300s acquire timeout is safety net. Not introduced by this change. |
| Multiple `st.rerun()` calls in fragment cause race conditions | Low | `st.rerun()` immediately stops fragment execution — only one rerun per execution |
| LangChain backend result arrives after timeout (between 120s-240s) | Low | If it arrives between timeout and 240s backend timeout, the task is already cancelled by the frontend — acceptable tradeoff for bounded UX wait |
| `render_message()` expander label change is missed | Low | Listed as explicit task in tasks.md |
| `return` after `st.rerun()` is unreachable — developer confusion | Low | Kept for defensive clarity and consistency with existing code patterns. Documented in comment. |
