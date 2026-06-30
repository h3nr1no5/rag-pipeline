## Context

The frontend Chat page (`client/pages/3_💬_Chat.py`) dispatches all selected RAG backends concurrently via `ThreadPoolExecutor(max_workers=3)` (lines 521-528). Each backend makes independent HTTP requests to the FastAPI server, which processes them in the async event loop. When a backend reaches the LLM generation step, it calls `MLXLLM.generate()` (`src/domain/services/llm.py` lines 235-286), which runs `mlx_lm.generate()` via `asyncio.to_thread()`.

With 3 concurrent backends (cosine, LangChain, LlamaIndex), all 3 call `generate()` within overlapping time windows — all hitting the same MLX model on Metal GPU. There is no concurrency lock, so Metal serializes inference at the hardware level. This causes GPU thrashing and makes total wall-clock time exceed the sum of individual pipeline times.

Phase 0 profiling baselines (with `test_pdf.pdf`, semantic chunking, `max_tokens=600`):
- LangChain individual: ~13.7s total (llm_generate 8.5s dominant)
- LlamaIndex individual: ~2.7s total (llm_generate 1.3s dominant)
- When both run concurrently + cosine = GPU contention overhead

## Goals / Non-Goals

**Goals:**
- Add `asyncio.Lock` to `MLXLLM.generate()` and `generate_stream()` to serialize concurrent GPU inference
- When N backends hit the LLM simultaneously, total wall-clock time ≈ sum(N generation times) but within a single-threaded queue model — eliminates contention overhead
- Preserve existing streaming and non-streaming APIs exactly (lock is transparent)
- Maintain existing timeout and error behavior

**Non-Goals:**
- Do NOT change the frontend ThreadPoolExecutor dispatch (already parallelized by `fix-rag-query-freezing`)
- Do NOT change the rendering order or add progressive result rendering (UX polish, separate concern)
- Do NOT change how the MLXLLM singleton is created or loaded
- Do NOT add connection pooling, request deduplication, or caching

## Decisions

### Decision 1: `asyncio.Lock` vs `threading.Lock`

**Chosen: `asyncio.Lock`**, acquired in the async `generate()` / `generate_stream()` method BEFORE `await asyncio.to_thread()`.

Rationale:
- `asyncio.Lock` prevents concurrent coroutines from even submitting to the thread pool — no unnecessary threads are spawned
- `threading.Lock` inside `asyncio.to_thread()` would still create N threads (only one runs, rest block on I/O)
- Since both `generate()` and `generate_stream()` are async methods that call `asyncio.to_thread()`, the lock is naturally acquired before the sync thread spawns
- With `asyncio.Lock`, other coroutines waiting on the lock release the event loop to serve other requests (health checks, etc.)

### Decision 2: Lock scope — wrap the entire `asyncio.to_thread()` call

```python
async def generate(self, prompt, max_tokens, temperature):
    # ... preamble (chat template, formatting) ...
    async with self._generate_lock:
        result = await asyncio.to_thread(
            generate, self._model, self._tokenizer, formatted_prompt, ...
        )
    return result
```

Rationale:
- Acquiring the lock before the thread spawn ensures only one MLX inference thread exists at any time
- The preamble (chat template, formatting, hashing) runs unlocked and can overlap between backends
- The lock scope does NOT include model loading (`_ensure_model_loaded`), which has its own `self._load_lock` — two different locks for two different resources

### Decision 3: No lock timeout (rely on existing MLX timeout)

Rationale:
- MLX `generate()` blocks until inference completes (bounded by `max_tokens` × ~50ms/token ≈ 200s worst case with 4096 tokens)
- Adding a second timeout layer adds complexity without clear benefit
- If a generation hangs, the existing `asyncio.wait_for()` or HTTP timeout catches it at the FastAPI level
- Lock ordering is trivial (single lock, no nesting)

### Decision 4: Lock is per-instance, not global

Since `MLXLLM` is a singleton (module-level `_llm_instance` in `llm.py`), an instance-level lock naturally serializes all concurrent access.

### Decision 5: Apply same lock to `generate_stream()` as well

The streaming path (`generate_stream()` → `stream_generate()`) uses the same GPU model. Without a lock, concurrent streaming calls would also contend. The `asyncio.Lock` ensures streaming is serialized too.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| **Reduced throughput for non-contended cases**: Serializing adds `await/async` overhead | `asyncio.Lock` is a Python-level primitive with ~1µs overhead — negligible vs multi-second MLX inference |
| **Head-of-line blocking**: One slow generation blocks all other backends | This already happens at the GPU level (Metal serializes implicitly). The lock makes it explicit and predictable. Total wall time is the same or better. |
| **Lock not released on exception**: If `asyncio.to_thread()` raises, the `async with` block ensures cleanup | Standard Python async context manager guarantees release on all exceptions |
| **Backends may hold lock longer than necessary**: Lock covers full `generate()` but retrieval/preparation runs unlocked | This is by design — retrieval is CPU-bound and should overlap |
