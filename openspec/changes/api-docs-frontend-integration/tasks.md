## 1. Database Model

- [ ] 1.1 Add `ApiDocIndex` table to `src/infrastructure/database/models.py` with columns: `document_id` (PK, FK), `domain_data` (JSON), `graph_data` (JSON), `embeddings` (JSON nullable), `embedding_dim` (Integer nullable), `created_at`
- [ ] 1.2 Add `api_doc_index` relationship to `Document` model for `back_populates`

## 2. Embedding Index — load_embeddings

- [ ] 2.1 Add `load_embeddings(embeddings: dict[str, list[float]], dimension: int) -> None` method to `ApiEmbeddingIndex` — rebuilds FAISS from stored vectors using pure numpy, no embedder model calls

## 3. Manager — Startup Recovery

- [ ] 3.1 Add `load_from_db(document_id, user_id, domain_data, graph_data, embeddings, embedding_dim)` to `ApiDocPipelineManager` — deserializes domain objects + chunk graph, rebuilds BM25 and FAISS indexes, stores in `_indexed_docs`
- [ ] 3.2 Add `load_all_from_db(async_session)` to `ApiDocPipelineManager` — queries all `api_doc_indexes` rows, calls `load_from_db` for each, logs count of loaded documents
- [ ] 3.3 Handle missing embeddings gracefully in `load_from_db` — if embeddings is None or embedding_dim mismatches, skip FAISS rebuild and fall back to BM25-only

## 4. API Doc Processor (New File)

- [ ] 4.1 Create `src/domain/services/api_doc_processor.py` with `_process_api_doc(document_id, file_path, doc_type)` function
- [ ] 4.2 Integrate extraction pipeline — call `DocxParser`/`PdfFallbackExtractor`, `TableDetector`, `DocumentConverter`, `ChunkGraphBuilder`, `ChunkTextFormatter`
- [ ] 4.3 Integrate embedding — call embedder, produce `{chunk_id: vector}` dict
- [ ] 4.4 Persist results — insert/update `ApiDocIndex` row with domain_data, graph_data, embeddings, embedding_dim
- [ ] 4.5 Update in-memory manager — call `_manager.ingest_docx`/`ingest_pdf` to build in-memory indexes for immediate querying

## 5. Processor Integration

- [ ] 5.1 Add `engine_type == "api-docs"` branch in `process_document_async()` — before standard parse/chunk/embed, route to `_process_api_doc()` from Step 4
- [ ] 5.2 Add `api_doc_processor.get_api_doc_processing_message()` for progress updates — "Extracting API documentation...", "Indexing chunks..."
- [ ] 5.3 Ensure `mark_document_failed` error handling works for the api-docs branch

## 6. Strategy Seeding + Upload Validation

- [ ] 6.1 In `main.py` lifespan, seed `api-docs` strategy (id="api-docs", name="API Documentation", engine_type="api-docs", is_system=True, chunk_size=0, etc.)
- [ ] 6.2 In `src/api/routes/documents.py`, add validation: `engine_type == "api-docs"` requires DOCX or PDF (reject .txt etc.)
- [ ] 6.3 Skip chunk_size/chunk_overlap/separators clamping when `engine_type == "api-docs"` (values are 0/[])

## 7. Route Changes — Deprecate Separate Ingest

- [ ] 7.1 Add deprecation warning log to `POST /query/api-docs/ingest` — log "DEPRECATED: Use POST /documents with strategy_id='api-docs' instead"
- [ ] 7.2 Optionally refactor ingest to delegate to standard document upload helper (reduces code duplication)

## 8. Frontend — Upload Page

- [ ] 8.1 Add "API Documentation" strategy to the upload page strategy dropdown
- [ ] 8.2 Hide chunk_size slider when "API Documentation" is selected
- [ ] 8.3 Hide chunk_overlap slider when "API Documentation" is selected
- [ ] 8.4 Hide separators input when "API Documentation" is selected
- [ ] 8.5 Hide use_hyperlinks checkbox when "API Documentation" is selected
- [ ] 8.6 Show informational note: "API documentation uses structure-aware extraction. Standard chunking parameters do not apply."

## 9. Frontend — Query Utility

- [ ] 9.1 Add `api_docs_query(api_base_url, token, query_text, document_id, top_k=10)` function to `client/utils/query.py`

## 10. Frontend — Chat Page

- [ ] 10.1 Check selected documents' strategies — if any have `engine_type="api-docs"`, show 4th "🔶 API Docs" checkbox
- [ ] 10.2 When "API Docs" is checked, route queries to `POST /api/v1/query/api-docs` with first API doc's document_id
- [ ] 10.3 Hide "API Docs" checkbox when no API doc documents are selected
- [ ] 10.4 Poll `GET /api/v1/query/api-docs/documents/{id}/status` to check if API doc manager has indexed the document (enable/disable checkbox based on `indexed` field)

## 11. Frontend — Response Display

- [ ] 11.1 Show confidence badge below answer (green ≥ 0.7, yellow ≥ 0.4, red < 0.4)
- [ ] 11.2 Show expandable sections for `relevant_functions` and `relevant_types` when non-empty
- [ ] 11.3 Handle API doc response format consistently alongside standard RAG responses
