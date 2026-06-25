## Context

The RAG query pipeline for API documentation uses a thread-pool bridge (`asyncio.to_thread()`) to run the DSPy `APIDocRAG.forward()` without blocking the main event loop. Inside that thread, retrieval calls `asyncio.run()` to create a fresh event loop for async embedding search.

The `SentenceTransformerEmbedder` singleton guard in `src/domain/services/embedding.py` uses `asyncio.Lock()` (line 20), which is bound to the main event loop at module import time. When `get_embedder()` is called from inside `asyncio.run()` in a thread, the `async with _embedder_lock` raises `RuntimeError` (cross-event-loop lock access on Python 3.11). This error is silently caught by a broad `except Exception` in `module.py:_forward_impl()`, producing a false "I could not find relevant information" answer.

The same latent bug exists in `CrossEncoderReRanker` (`retrieval_langchain.py` line 69: `_lock = asyncio.Lock()`), currently masked by the eager warmup in step 1 of `_load_models()`.

The existing `MLXLLM` class (`llm.py` line 97) demonstrates the correct pattern: `threading.Lock()` with a synchronous double-checked loading function, callable from any event loop via `asyncio.to_thread()`.

## Goals / Non-Goals

**Goals:**
- Eliminate the cross-event-loop `RuntimeError` in the embedder singleton guard
- Make the same fix in `CrossEncoderReRanker` for consistency
- Narrow the silent exception swallowing in `_forward_impl()` to let unexpected errors reach the DSPy circuit-breaker
- Preserve the public async API (`await get_embedder()` must continue to work)
- All existing tests must pass without modification

**Non-Goals:**
- Refactoring the `asyncio.run()` inside `asyncio.to_thread()` pattern (larger architectural change, out of scope)
- Adding integration tests for this specific race (hard to reproduce deterministically)
- Changing the warmup timing or ordering

## Decisions

### Decision 1: Replace `asyncio.Lock()` with `threading.Lock()` + sync loader in `embedding.py`

**Decision**: Split `get_embedder()` into a synchronous `_load_embedder_sync()` function guarded by `threading.Lock()`, and a thin async `get_embedder()` wrapper that delegates to `asyncio.to_thread(_load_embedder_sync)`.

**Rationale**:
- `threading.Lock()` has no event-loop affinity — it works from any thread, any event loop, or no event loop
- Matches the established `MLXLLM._ensure_model_loaded()` pattern (double-checked locking with `threading.Lock()`)
- `asyncio.to_thread()` handles the synchronous model construction without blocking the calling context
- After the first load, `_embedder_instance` is set and `get_embedder()` returns instantly without touching the lock

**Alternatives considered**:
- *Keep `asyncio.Lock()` but defer module import*: Doesn't work — `hybrid_retriever.py` eagerly imports `normalize_scores` from `embedding.py` at module level during lifespan startup, which executes the lock creation in the main loop.
- *Make the DSPy pipeline fully async*: Larger footprint, requires changing `module.forward()` to `async def`, altering `_query_dspy()` and the LM adapter. High-risk refactor.
- *Move the lock creation to first-use time via lazy initialization*: `asyncio.Lock()` would still be bound to whichever event loop happens to be running during first use, creating a different non-deterministic race.

### Decision 2: Apply same pattern to `CrossEncoderReRanker._lock` in `retrieval_langchain.py`

**Decision**: Replace `CrossEncoderReRanker._lock` (class-level `asyncio.Lock()` at line 69) with `threading.Lock()`, and refactor `_ensure_model()` to use a synchronous inner loader.

**Rationale**:
- Same root cause — `asyncio.Lock()` accessed from different event loops
- Currently masked by eager warmup in `_load_models()` step 1, but if warmup fails or the model is reset, the first query from a thread would hit the same `RuntimeError`
- Consistency with the embedder pattern

### Decision 3: Narrow the exception handler in `module.py:_forward_impl()`

**Decision**: Change `except Exception:` (line 195) to `except (ValueError, asyncio.TimeoutError, RetrievalError):` — catch only expected retrieval failures. Let unexpected errors propagate to the DSPy circuit-breaker in `_query_dspy()`, which falls back to prompt-based generation.

**Rationale**:
- The broad `except Exception` masked the cross-loop `RuntimeError`, making debugging extremely difficult
- After the lock fix, unexpected errors (e.g., model loading failures, infrastructure errors) should NOT produce a misleading "I could not find relevant information" message — they should trigger the fallback path
- The DSPy circuit-breaker in `manager.py:_query_dspy()` already handles exceptions from `module.forward()` by logging + falling back to `_query_fallback()`

**Alternatives considered**:
- *Keep the broad catch*: Would continue to mask unexpected errors. Defeats debugging.
- *Log the full exception and re-raise*: Same as propagating, but would skip the fallback path.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| `SentenceTransformerEmbedder()` constructor blocks the calling thread | Already true today — the constructor loads the model synchronously. `asyncio.to_thread()` in the wrapper ensures it doesn't block the event loop. |
| Double-checked locking with `threading.Lock()` has subtle Python GIL semantics | Python's GIL protects dict/set operations, but the pattern is well-established (`MLXLLM._ensure_model_loaded()` uses the same). The outer `if _embedder_instance is None` check is a performance optimization; correctness is guaranteed by the lock. |
| Existing callers that `await get_embedder()` from the main event loop may see a thread switch | Unchanged from current behavior — `get_embedder()` already uses `asyncio.to_thread()` for the underlying model construction. |
| `CrossEncoderReRanker._ensure_model()` becomes sync internally but is still called with `await` | No behavioral change for callers. The method remains `async def` but now delegates to a sync inner function via `asyncio.to_thread()` if the model hasn't loaded yet. |
