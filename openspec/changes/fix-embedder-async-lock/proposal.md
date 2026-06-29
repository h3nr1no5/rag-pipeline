## Why

The first RAG query against indexed API documentation always returns "I could not find relevant information in the API documentation", while the identical query on the second attempt succeeds. This is caused by a cross-event-loop `asyncio.Lock()` violation: the embedder singleton uses an `asyncio.Lock()` created in the main event loop, but the DSPy pipeline runs retrieval inside `asyncio.run()` in a thread pool, creating a separate event loop. On Python 3.11, accessing an `asyncio.Lock()` from a different event loop raises `RuntimeError`, which is silently swallowed by a broad exception handler, producing a false "no relevant information" answer.

## What Changes

- **`src/domain/services/embedding.py`**: Replace `asyncio.Lock()` with `threading.Lock()` for the embedder singleton guard, matching the pattern already used by `MLXLLM._ensure_model_loaded()`. Refactor `get_embedder()` into a synchronous loader function (callable via `asyncio.to_thread()`) and a thin async wrapper.
- **`src/domain/services/retrieval_langchain.py`**: Replace `asyncio.Lock()` with `threading.Lock()` in `CrossEncoderReRanker` for consistency (currently masked by eager warmup, but same latent bug).
- **`src/domain/rag/api_docs/pipeline/module.py`**: Narrow the broad `except Exception` in `_forward_impl()` to only catch expected retrieval errors, letting unexpected errors propagate to the DSPy circuit-breaker fallback.

## Capabilities

### New Capabilities
- `embedder-lock-fix`: Replace `asyncio.Lock()` with `threading.Lock()` in both `SentenceTransformerEmbedder` singleton guard and `CrossEncoderReRanker` singleton guard, with a synchronous loader pattern that is loop-agnostic.

### Modified Capabilities
- *(no existing spec-level requirements are changing)*

## Impact

- **Affected files**: `src/domain/services/embedding.py`, `src/domain/services/retrieval_langchain.py`, `src/domain/rag/api_docs/pipeline/module.py`
- **Dependencies**: None (uses existing `threading` module already imported in the project)
- **Backward compatibility**: Fully backward compatible — the public API (`get_embedder()`) remains `async def` with the same signature.
- **Testing**: Existing embedder and retrieval tests should continue to pass; the race condition was timing-dependent and not caught by existing tests.
