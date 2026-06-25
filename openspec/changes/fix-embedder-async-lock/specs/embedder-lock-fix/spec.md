## ADDED Requirements

### Requirement: Embedder singleton SHALL use threading.Lock()

The `SentenceTransformerEmbedder` singleton guard in `src/domain/services/embedding.py` SHALL use `threading.Lock()` instead of `asyncio.Lock()` to protect the double-checked lazy initialization. A synchronous `_load_embedder_sync()` function SHALL perform the actual model construction under the lock. The public `async def get_embedder()` SHALL delegate to `_load_embedder_sync()` via `asyncio.to_thread()` when the embedder has not yet been loaded, and return the cached instance directly when it has.

**Rationale**: `threading.Lock()` has no event-loop affinity and works correctly from any thread or event loop, unlike `asyncio.Lock()` which raises `RuntimeError` when accessed from a different event loop than the one it was created in.

#### Scenario: First call from a thread loads the embedder
- **WHEN** `get_embedder()` is called for the first time from inside `asyncio.run()` in a thread pool thread
- **AND** `_embedder_instance` is `None`
- **THEN** `_load_embedder_sync()` is called via `asyncio.to_thread()`
- **AND** the `threading.Lock()` is acquired without raising `RuntimeError`
- **AND** `SentenceTransformerEmbedder()` is constructed
- **AND** `_embedder_instance` is set to the new instance
- **AND** the instance is returned to the caller

#### Scenario: Second call from any context returns cached instance
- **WHEN** `get_embedder()` is called a second time from any event loop or thread
- **AND** `_embedder_instance` is not `None`
- **THEN** `_embedder_instance` is returned immediately without acquiring any lock

#### Scenario: Concurrent first calls are serialized
- **WHEN** two threads call `get_embedder()` concurrently with `_embedder_instance` being `None`
- **THEN** only one `SentenceTransformerEmbedder()` is constructed
- **AND** the same instance is returned to both callers

### Requirement: CrossEncoderReRanker singleton SHALL use threading.Lock()

The `CrossEncoderReRanker` class in `src/domain/services/retrieval_langchain.py` SHALL replace its `asyncio.Lock()` with `threading.Lock()` for the model loading guard. The `_ensure_model()` async method SHALL delegate model construction to a synchronous inner function under the `threading.Lock()`.

**Rationale**: Same cross-event-loop issue as the embedder — the cross-encoder model is loaded from inside `asyncio.run()` in a thread during retrieval. Currently masked by eager warmup, but the latent bug exists.

#### Scenario: Cross-encoder loads from thread without RuntimeError
- **WHEN** `CrossEncoderReRanker._ensure_model()` is called for the first time from inside `asyncio.run()` in a thread pool thread
- **AND** `self._model` is `None`
- **THEN** the `threading.Lock()` is acquired without raising `RuntimeError`
- **AND** the `CrossEncoder` model is constructed
- **AND** `self._model` is set to the new instance

### Requirement: Retrieval exception handler SHALL NOT swallow unexpected errors

The `_forward_impl()` method in `src/domain/rag/api_docs/pipeline/module.py` SHALL narrow its retrieval exception handler from `except Exception` to only catch expected retrieval errors (`ValueError`, `asyncio.TimeoutError`). Unexpected errors SHALL propagate to the caller (`_query_dspy()`), which SHALL catch them and fall back to the prompt-based generation path.

**Rationale**: The broad `except Exception` masked the cross-event-loop `RuntimeError`, producing a misleading "not found" answer instead of triggering the fallback. Narrowing the catch surfaces unexpected errors for debugging and correct fallback behavior.

#### Scenario: Unexpected error triggers circuit-breaker fallback
- **WHEN** `self.hybrid_retriever.retrieve()` raises an unexpected exception (e.g., `RuntimeError`)
- **THEN** the exception propagates out of `_forward_impl()` and `forward()`
- **AND** the exception is re-raised by `asyncio.to_thread()` in `_query_dspy()`
- **AND** the DSPy circuit-breaker in `_query_dspy()` catches the exception
- **AND** the pipeline falls back to `_query_fallback()` for answer generation

#### Scenario: Expected retrieval errors are handled gracefully
- **WHEN** `self.hybrid_retriever.retrieve()` raises `ValueError` or `asyncio.TimeoutError`
- **THEN** the warning is logged and execution continues with available chunks
- **AND** the pipeline returns the "I could not find relevant information" answer only if no chunks were retrieved
