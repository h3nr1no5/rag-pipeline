## Why

The existing API Doc RAG pipeline has a complete backend (DOCX extraction, hierarchical chunking, BM25+FAISS retrieval, DSPy generation) but is invisible to users — it has no frontend integration and its in-memory indexes are lost on every server restart, requiring on-the-fly re-indexing on first query. This change makes API documentation querying a first-class feature: users upload API docs alongside normal documents, the pipeline state persists across restarts, and the frontend lets users select and query API docs like any other RAG backend.

## What Changes

- **New `api-docs` chunking strategy** — seeded as a system strategy with `engine_type="api-docs"`. Replaces the old removed `is_api_doc` flag.
- **Processor routing** — `process_document_async()` branches on `engine_type="api-docs"` to run the dedicated extraction/chunking pipeline instead of standard recursive/semantic chunking.
- **Database persistence** — New `api_doc_indexes` table stores the extracted domain objects, chunk graph, and embedding vectors. Survives server restarts without re-indexing.
- **Startup recovery** — `ApiDocPipelineManager` loads persisted data from the DB on startup, rebuilding BM25 and FAISS indexes from stored data (no embedder model calls).
- **Deprecated `/query/api-docs/ingest`** — Users upload through the standard `POST /documents` endpoint with `strategy_id="api-docs"`. The separate ingest endpoint remains for backward compatibility with a deprecation warning.
- **Frontend strategy selector** — "API Documentation" option in the upload strategy dropdown hides irrelevant chunking params (chunk_size, chunk_overlap, separators).
- **Frontend chat** — 4th "API Docs" backend selector appears when API doc documents are selected. Queries route to `/query/api-docs`.
- **Frontend response display** — Richer source display for API doc responses (confidence badge, function/type references).

## Capabilities

### New Capabilities
- `api-doc-persistence`: Database-backed storage of API doc extraction results (domain objects, chunk graph, embeddings) with startup recovery.
- `api-docs-frontend`: Frontend integration — strategy selection, document routing, 4th backend checkbox, richer response display.
- `api-docs-strategy`: "API Documentation" chunking strategy with `engine_type="api-docs"` and processor routing.

### Modified Capabilities
- `processing-config`: The processing pipeline gains a new `engine_type="api-docs"` branch. Upload validation allows DOCX/PDF for this strategy (no chunk_size/overlap restrictions).
- `frontend-loading-status`: Chat page needs to reflect API doc indexing status differently (in-memory manager state vs DB status).

## Impact

- **Backend**: New `api_doc_indexes` SQLAlchemy model. `ApiDocPipelineManager` gains `load_from_db()`/`load_all_from_db()`. `ApiEmbeddingIndex` gains `load_embeddings()` for FAISS rebuild from stored vectors. Processor branches for `engine_type="api-docs"`.
- **Frontend**: Upload page strategy dropdown, chat page 4th checkbox, richer response display, new query utility.
- **API**: `POST /documents` accepts `strategy_id="api-docs"` for DOCX/PDF. `POST /query/api-docs/ingest` deprecated.
- **Data**: New `api_doc_indexes` table (one row per API doc document). ~15-80 KB per document.
