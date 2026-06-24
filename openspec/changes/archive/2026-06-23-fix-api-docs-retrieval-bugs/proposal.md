## Why

Two bugs in the API documentation RAG pipeline prevent users from finding relevant content through natural-language queries. Method names using camelCase (e.g., `StartSelection`) are indexed as single tokens by BM25, so queries that split them into separate words ("start", "selection") never match. Separately, the in-memory index is lost on every server restart because `load_all_from_db()` was never wired into the application startup — forcing an unreliable on-the-fly re-ingestion on the first query.

## What Changes

- **Fix BM25 camelCase tokenization**: Replace whitespace-only tokenizer with one that splits on camelCase boundaries (lowercase→uppercase transitions). `StartSelection` → `["start", "selection"]` in the index, matching user queries.
- **Wire `load_all_from_db()` into application startup**: Call `ApiDocPipelineManager.load_all_from_db()` during the lifespan startup so persisted API doc indexes are restored to memory without re-processing source files.
- **Add integration tests**: Verify both fixes with realistic query scenarios.

## Capabilities

### New Capabilities

*(none — this is a bug-fix change to existing capabilities)*

### Modified Capabilities

- **api-docs-rag**: BM25 keyword index tokenization — change from whitespace-only to camelCase-aware tokenization. This is an implementation change to the existing `ApiBm25Index` that affects retrieval behavior but does not change the public API of the index.
- **api-docs-rag**: Application startup lifecycle — add `load_all_from_db()` call during `lifespan` startup. This is an operational change that eliminates the need for on-the-fly re-ingestion after server restarts.

## Impact

| Area | Impact |
|------|--------|
| `src/domain/rag/api_docs/retrieval/bm25_index.py` | Tokenization logic changed in `_build_keyword_text` and search — all BM25 indexes rebuilt on next ingestion |
| `src/api/main.py` | New import and call to `ApiDocPipelineManager.load_all_from_db()` in the `lifespan` startup block |
| `src/domain/rag/api_docs/manager.py` | No changes needed (function exists) |
| Tests | New integration tests for BM25 query matching with camelCase method names |
| Dependencies | No new dependencies |
| Existing API docs data | BM25 indexes are rebuilt on next `add_graph()` call — existing persisted data in `ApiDocIndex` table is unaffected |
