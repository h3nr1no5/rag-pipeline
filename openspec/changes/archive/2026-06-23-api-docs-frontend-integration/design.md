## Context

The project has two parallel RAG systems:

- **Standard RAGs** (cosine, LangChain, LlamaIndex): Documents uploaded via `POST /documents` → recursive/semantic chunking → `Chunk` table with stored embeddings → query-time retrieval. Fully persisted in SQLite, survives restarts.
- **API Doc RAG**: Documents uploaded via `POST /query/api-docs/ingest` → specialized DOCX table parsing → domain objects (`APIInterface`, `APIEnum`, `APIErrorCode`) → hierarchical `ChunkGraph` → in-memory BM25 + FAISS indexes. **All in-memory** — indexes lost on restart, rebuilt on-demand on first query (3-15s latency spike).

The old `api-docs` chunking strategy and `is_api_aware` column were already removed/migrated to `semantic` strategy in `main.py`. There is currently no routing signal connecting the standard upload flow to the API Doc pipeline.

The API Doc RAG already has its own routes at `/query/api-docs` with complete query logic. What's missing: (1) ability to upload through the standard endpoint, (2) database persistence, (3) frontend integration.

## Goals / Non-Goals

**Goals:**
- Add `api-docs` as a system chunking strategy with `engine_type="api-docs"`
- Route documents with this strategy through the API Doc extraction pipeline (not standard chunking)
- Persist extraction results (domain objects, chunk graph, embeddings) to SQLite
- Rebuild in-memory indexes from DB on startup — no embedder model calls needed
- Deprecate the separate `/query/api-docs/ingest` endpoint
- Add frontend support: strategy selector, 4th backend checkbox, richer response display

**Non-Goals:**
- Merging the API Doc retrieval pipeline into the standard query routes — `/query/api-docs` remains separate
- Streaming support for API doc queries
- Normalizing domain objects into fully relational tables (JSON blobs are sufficient since data is only used to rebuild in-memory indexes)
- Changing the DSPy module or the hybrid retriever logic

## Decisions

### D1: Dedicated `ApiDocIndex` table vs cramming into `Document.api_spec`

**Decision**: New `api_doc_indexes` table with JSON columns for domain_data, graph_data, and embeddings.

**Rationale**: The existing `Document.api_spec` JSON column exists but was designed for OpenAPI specs. Using it would mix concerns and the existing serialization mechanism (Pydantic → dict → JSON) is the same either way. A dedicated table provides:
- Clear ownership and schema documentation
- Easier querying: `SELECT * FROM api_doc_indexes` vs filtering by non-null api_spec
- Cleaner migration path (no type conflicts with api_spec's original purpose)
- The serializer module (`serializer.py`) already has `serialize_chunk_graph`/`deserialize_chunk_graph` — minimal new code

### D2: Storing embedding vectors vs recomputing on startup

**Decision**: Store embedding vectors as a JSON dict `{chunk_id: [float, ...]}` in the `embeddings` column. Rebuild FAISS from stored vectors on startup.

**Rationale**: This mirrors the standard RAG pipeline, which stores `Chunk.embedding` as JSON and loads them on every query. For API docs, storing vectors means:
- Startup rebuild is pure numpy — ~1ms per document
- No embedder model calls during startup (important: the embedder is loaded lazily and may not be ready)
- Storage cost is negligible: a 384-dim vector is ~3KB JSON. 500 chunks = ~1.5MB.
- The `ApiEmbeddingIndex` can expose a `load_embeddings(embeddings: dict, dim: int)` method that skips the embedder entirely.

*Alternative considered*: Store FAISS index as binary blob. Rejected because SQLite handles JSON natively, and the chunk_id → vector mapping is simpler to debug as JSON.

### D3: Processor integration — new branch vs new processor

**Decision**: Add an `if engine_type == "api-docs"` branch early in `process_document_async()`, before standard parse/chunk/embed loops.

**Rationale**: The processor is the single dispatch point for all document processing. A new branch is clean, doesn't affect existing flows, and reuses the progress tracking infrastructure (`update_document_progress`, `mark_document_failed`). The actual extraction pipeline lives in a new `src/domain/services/api_doc_processor.py` to keep `processor.py` from growing too large.

### D4: Deprecation strategy for `/query/api-docs/ingest`

**Decision**: Keep the endpoint but log a deprecation warning. Implement as an internal redirect that calls the same helper as the standard upload endpoint.

**Rationale**: Immediate removal would break existing workflows. A deprecation period with warnings lets users migrate. The code change is minimal: instead of duplicating upload logic, the ingest handler delegates to the standard document upload helper.

### D5: Frontend — strategy as implicit routing

**Decision**: The chunking strategy is the sole routing signal. When a user selects "API Documentation" during upload, the document gets `chunking_strategy_id="api-docs"`. On the chat page, selected documents' strategies are checked — if any have `engine_type="api-docs"`, the "API Docs" checkbox appears.

**Rationale**: No separate `is_api_doc` flag needed. The strategy is the source of truth. This also means re-uploading with a different strategy is naturally supported (reprocess with standard chunking = treat as flat text).

## Risks / Trade-offs

- **[Risk] Embedding dimension mismatch**: If the embedding model changes (via config), stored vectors from `api-docs` docs will have different dimensions than newly processed docs. → **Mitigation**: Store `embedding_dim` in the table. On startup, skip FAISS rebuild if dimension doesn't match current model (fall back to on-the-fly re-indexing, with a warning log).
- **[Risk] Startup performance**: Loading all API doc indexes and rebuilding FAISS for each adds ~1-10ms per doc. With ~50 docs this is still under a second. → **Mitigation**: Acceptable. If it becomes an issue, lazy-load per document on first query.
- **[Risk] Embedding model not ready during startup**: The embedder model is loaded asynchronously during warmup. The FAISS rebuild needs vectors already stored, so no embedder calls are needed — pure numpy. No risk.
- **[Trade-off] No chunking params for API docs**: `chunk_size`, `chunk_overlap`, `separators` are meaningless for the API Doc pipeline since it uses structure-aware extraction. The frontend hides these fields when "API Documentation" is selected, which is a good UX but may surprise users who expect to configure chunking.
- **[Trade-off] Separate query endpoint**: `/query/api-docs` has its own schema (`ApiDocQueryRequest` with `document_id` instead of `document_ids[]`). This is architecturally clean but means the frontend needs a separate query path for API docs. The alternative (unifying schemas) would require changes to the DSPy module and retriever — not worth it given the different response format (confidence, relevant_functions, relevant_types).
