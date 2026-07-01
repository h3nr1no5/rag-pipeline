## Why

A comprehensive asyncio audit (31 source files) revealed critical event-loop lifecycle bugs, recurring anti-patterns, and performance bottlenecks that can cause runtime crashes, data corruption, and degraded throughput. The most critical issue — `asyncio.run()` called inside `asyncio.to_thread()` in the DSPy RAG pipeline — creates cross-event-loop state that will silently corrupt data or crash if any async resource (aiosqlite, asyncio.Lock) is ever shared. Additional issues compound: per-chunk SQLite commits create unnecessary fsync pressure, N+1 queries degrade cache-hit latency, and synchronous file I/O blocks the event loop. These need fixing before they manifest as production incidents.

## What Changes

1. **Fix DSPy event-loop lifecycle** (`module.py`, `lm_adapter.py`, `manager.py`): Eliminate the `asyncio.run()` inside `asyncio.to_thread()` pattern by making the DSPy pipeline fully async.
2. **Batch per-chunk SQLite commits** (`processor.py`): Reduce from N commits per document to N/batch_size, reducing fsync overhead during document processing.
3. **Offload sync file I/O to aiofiles** (`documents.py`, `api_docs/routes.py`): Prevent event-loop blocking on file writes.
4. **Fix N+1 chunk queries in cache-hit paths** (`query/routes.py`): Replace N individual SELECT queries with a single `id.in_(...)` query across all 6 cache-hit locations.
5. **Fix silent empty-return in CustomEnsembleRetriever** (`retrieval_langchain.py`): Raise a clear error instead of returning `[]` when called from a running event loop.
6. **Batch cross-encoder scoring** (`verification.py`): Collect all sentence-source pairs into a single `model.predict()` call.
7. **Consolidate redundant DB sessions** (`processor.py`): Eliminate unnecessary session churn in the processing loop.
8. **Remove redundant inline asyncio imports** (`parsers/base.py`): Clean up 6 duplicate `import asyncio` inside method bodies.

## Capabilities

### New Capabilities
- *(None — all changes are modifications to existing code, not new capabilities)*

### Modified Capabilities
- `document-processing-lifecycle`: Per-chunk commit behavior changes to batched commits; session management simplified
- `retrieval`: `CustomEnsembleRetriever._get_relevant_documents()` changes from silent empty-return to explicit error
- `response-verification`: Cross-encoder scoring batched for performance
- `api-docs-rag`: DSPy pipeline event-loop pattern changed from sync bridge to fully async

## Impact

| Area | Impact |
|------|--------|
| `src/domain/rag/api_docs/pipeline/module.py` | `APIDocRAG.forward()` becomes `async def forward()` |
| `src/domain/rag/api_docs/pipeline/lm_adapter.py` | `DSPyLLMAdapter` becomes async-aware, removes `asyncio.run()` |
| `src/domain/rag/api_docs/pipeline/manager.py` | `_query_dspy()` calls `await` instead of `asyncio.to_thread()` |
| `src/domain/services/processor.py` | Commit batching logic; session consolidation |
| `src/domain/services/verification.py` | Batch cross-encoder prediction |
| `src/domain/services/retrieval_langchain.py` | Error-throwing in `_get_relevant_documents()` |
| `src/api/routes/documents.py` | Sync file I/O → aiofiles |
| `src/api/routes/query/routes.py` | N+1 chunk queries → batched queries (6 locations) |
| `src/domain/rag/api_docs/routes.py` | Sync file I/O → aiofiles |
| `src/infrastructure/parsers/base.py` | Remove 6 redundant `import asyncio` |
| `pyproject.toml` | Add `aiofiles` dependency |
