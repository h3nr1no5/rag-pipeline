## 1. Setup

- [x] 1.1 Add `dspy>=2.6` and `python-docx>=1.1` to pyproject.toml and run `uv sync`
- [x] 1.2 Create `src/domain/rag/api_docs/` module structure with `__init__.py`
- [x] 1.3 Add `API_DOCS_ENABLED` setting to `src/core/config.py` (default: True)

## 2. Domain Model

- [x] 2.1 Define `APIParameter`, `APIFunction`, `APIProperty`, `APIInterface`, `APIEnum`, `APIEnumValue`, `APIErrorCode` as pydantic BaseModel classes in `api_docs/model/`
- [x] 2.2 Define `ChunkNode` dataclass with `chunk_id`, `parent_id`, `child_ids`, `kind`, `level`, `source_doc`, `content`, `metadata` for the chunk graph

## 3. DOCX Extraction

- [x] 3.1 Implement `DocxParser` that reads DOCX files with `python-docx` and extracts tables, paragraphs, and headings as raw structures
- [x] 3.2 Implement table column detection: identify method tables, property tables, enum tables, error code tables by column headers
- [x] 3.3 Implement multi-row function merging: detect functions spanning multiple table rows and merge into single `APIFunction`
- [x] 3.4 Implement paragraph extraction with heading hierarchy preservation
- [x] 3.5 Build `DocumentConverter` that converts raw extracted structures into typed domain objects
- [x] 3.6 Implement `PdfFallbackExtractor` that falls back to existing pdfminer pipeline when DOCX is unavailable

## 4. API Chunking

- [x] 4.1 Implement `ChunkGraphBuilder` that converts domain objects into parent-child chunk graph
- [x] 4.2 Implement chunk metadata enrichment (chunk_id, parent_id, kind, level, source_doc, interface_name, function_name)
- [x] 4.3 Implement chunk graph serialization to JSON and deserialization for persistence
- [x] 4.4 Implement chunk text formatting: convert each domain object into the text that gets embedded and retrieved

## 5. API Retrieval

- [x] 5.1 Implement `ApiBm25Index` that indexes function names, parameter names, type names, and error code names for exact-match retrieval
- [x] 5.2 Implement embedding index integration: reuse `SentenceTransformerEmbedder` to embed chunk text content into FAISS
- [x] 5.3 Implement `RrfFusion` to merge BM25 and embedding results using Reciprocal Rank Fusion (k=60)
- [x] 5.4 Implement `LinkTraverser` that detects type cross-references in results and appends referenced parent chunks (max depth 2)
- [x] 5.5 Implement `ParentExpander` that includes parent/grandparent chunks when child chunks are retrieved
- [x] 5.6 Implement `HybridRetriever` that orchestrates BM25, embedding, RRF, link traversal, and parent expansion

## 6. DSPy LM Adapter

- [x] 6.1 Implement `MLXDspyLM` class inheriting `dspy.BaseLM`, wrapping `MLXLLM` singleton
- [x] 6.2 Implement `forward()` and `__deepcopy__` methods
- [x] 6.3 Configure DSPy default LM during application initialization in `src/api/main.py`

## 7. DSPy Pipeline

- [x] 7.1 Define DSPy signatures: `QueryAnalyzer`, `ContextAssembler`, `APIResponseGenerator`
- [x] 7.2 Implement `APIDocRAG` module (`dspy.Module`) that orchestrates query analysis, retrieval, context assembly, and generation
- [x] 7.3 Implement DSPy assertions for quality (citation presence, function reference validation)
- [x] 7.4 Implement evaluation metrics: `retrieval_recall`, `citation_accuracy`, `hallucination_rate` (compatible with `dspy.Evaluate`)

## 8. API Route and Integration

- [x] 8.1 Implement `/api/v1/query/api-docs` FastAPI route with `query` and `document_id` parameters
- [x] 8.2 Implement request/response models using pydantic (`ApiDocQueryRequest`, `ApiDocQueryResponse`)
- [x] 8.3 Implement ingestion route for DOCX upload that triggers extraction → chunking → indexing pipeline
- [x] 8.4 Wire ingestion into the existing document processing flow (as standalone endpoint with DB document record)
- [x] 8.5 Implement error handling and logging for the new pipeline

## 9. Testing

- [x] 9.1 Write unit tests for domain model validation (malformed types, empty strings, missing optional fields)
- [x] 9.2 Write unit tests for DOCX table parser with synthetic DOCX fixtures (method tables, multi-row functions, property tables)
- [x] 9.3 Write unit tests for chunk graph builder (parent-child hierarchy, serialization round-trip)
- [x] 9.4 Write unit tests for hybrid retriever (BM25 scoring, RRF fusion, link traversal depth limiting)
- [x] 9.5 Write unit tests for DSPy signatures and module (mock LM, verify structured output)
- [x] 9.6 Write integration test for full pipeline: upload DOCX → chunk → query → verify response has citations
- [x] 9.7 Write integration test for PDF fallback path

## 10. Security Hardening

- [x] 10.1 **CRITICAL: File type validation** — Added magic byte validation for DOCX (`PK\x03\x04`) and PDF (`%PDF`) in `routes.py`. Also validates MIME type from `UploadFile.content_type` when available.
- [x] 10.2 **CRITICAL: Path traversal prevention** — Added `os.path.basename()` to strip directory components, `os.path.realpath()` resolution, and `_is_safe_path()` check to verify the resolved path stays within `settings.upload_dir`.
- [x] 10.3 **CRITICAL: DoS via memory exhaustion** — Added early size check using `UploadFile.size` before reading content, plus in-memory size validation after read. Maximum size is enforced before processing.
- [x] 10.4 **HIGH: Cross-user data leak** — Changed `_indexed_docs` key from `(document_id)` to `(user_id, document_id)` tuple. All `ApiDocPipelineManager` methods now accept `user_id`. The `/documents` list endpoint filters by the calling user.
- [x] 10.5 **HIGH: Rate limiting** — Added `_RateLimiter` sliding-window class (30 req/60s per user, per endpoint) applied to both `/ingest` and query endpoints.
- [x] 10.6 **HIGH: Error message leakage** — Replaced detailed error messages with user-safe generic text. Full details are logged server-side with `exc_info=True`. Updated both the ingest and query endpoints, plus `_run_on_the_fly_ingestion`.
- [x] 10.7 **HIGH: Temp file cleanup** — Added `try/finally` block in the ingest endpoint that removes the uploaded file if the ingestion pipeline fails (tracked via `_ingestion_succeeded` flag).
- [x] 10.8 **HIGH: DSPy global state** — Added docstring note in `main.py` explaining that `dspy.configure()` uses global state, the singleton pattern makes it idempotent, and `dspy.settings.context()` is the escape hatch for per-request overrides.
- [x] 10.9 **CODE REVIEW: DocxParser error handling** — Wrapped `Document(str(self.file_path))` in try/except, raising `ValueError` with context on parse failure.
- [x] 10.10 **CODE REVIEW: PdfFallbackExtractor resource leak** — Moved `doc.close()` into a `try/finally` block to ensure the PDF document is always closed on exception.
