## 1. Setup

- [ ] 1.1 Add `dspy>=2.6` and `python-docx>=1.1` to pyproject.toml and run `uv sync`
- [ ] 1.2 Create `src/domain/rag/api_docs/` module structure with `__init__.py`
- [ ] 1.3 Add `API_DOCS_ENABLED` setting to `src/core/config.py` (default: True)

## 2. Domain Model

- [ ] 2.1 Define `APIParameter`, `APIFunction`, `APIProperty`, `APIInterface`, `APIEnum`, `APIEnumValue`, `APIErrorCode` as pydantic BaseModel classes in `api_docs/model/`
- [ ] 2.2 Define `ChunkNode` dataclass with `chunk_id`, `parent_id`, `child_ids`, `kind`, `level`, `source_doc`, `content`, `metadata` for the chunk graph

## 3. DOCX Extraction

- [ ] 3.1 Implement `DocxParser` that reads DOCX files with `python-docx` and extracts tables, paragraphs, and headings as raw structures
- [ ] 3.2 Implement table column detection: identify method tables, property tables, enum tables, error code tables by column headers
- [ ] 3.3 Implement multi-row function merging: detect functions spanning multiple table rows and merge into single `APIFunction`
- [ ] 3.4 Implement paragraph extraction with heading hierarchy preservation
- [ ] 3.5 Build `DocumentConverter` that converts raw extracted structures into typed domain objects
- [ ] 3.6 Implement `PdfFallbackExtractor` that falls back to existing pdfminer pipeline when DOCX is unavailable

## 4. API Chunking

- [ ] 4.1 Implement `ChunkGraphBuilder` that converts domain objects into parent-child chunk graph
- [ ] 4.2 Implement chunk metadata enrichment (chunk_id, parent_id, kind, level, source_doc, interface_name, function_name)
- [ ] 4.3 Implement chunk graph serialization to JSON and deserialization for persistence
- [ ] 4.4 Implement chunk text formatting: convert each domain object into the text that gets embedded and retrieved

## 5. API Retrieval

- [ ] 5.1 Implement `ApiBm25Index` that indexes function names, parameter names, type names, and error code names for exact-match retrieval
- [ ] 5.2 Implement embedding index integration: reuse `SentenceTransformerEmbedder` to embed chunk text content into FAISS
- [ ] 5.3 Implement `RrfFusion` to merge BM25 and embedding results using Reciprocal Rank Fusion (k=60)
- [ ] 5.4 Implement `LinkTraverser` that detects type cross-references in results and appends referenced parent chunks (max depth 2)
- [ ] 5.5 Implement `ParentExpander` that includes parent/grandparent chunks when child chunks are retrieved
- [ ] 5.6 Implement `HybridRetriever` that orchestrates BM25, embedding, RRF, link traversal, and parent expansion

## 6. DSPy LM Adapter

- [ ] 6.1 Implement `MLXDspyLM` class inheriting `dspy.BaseLM`, wrapping `MLXLLM` singleton
- [ ] 6.2 Implement `forward()` and `__deepcopy__` methods
- [ ] 6.3 Configure DSPy default LM during application initialization in `src/api/main.py`

## 7. DSPy Pipeline

- [ ] 7.1 Define DSPy signatures: `QueryAnalyzer`, `ContextAssembler`, `APIResponseGenerator`
- [ ] 7.2 Implement `APIDocRAG` module (`dspy.Module`) that orchestrates query analysis, retrieval, context assembly, and generation
- [ ] 7.3 Implement DSPy assertions for quality (citation presence, function reference validation)
- [ ] 7.4 Implement evaluation metrics: `retrieval_recall`, `citation_accuracy`, `hallucination_rate` (compatible with `dspy.Evaluate`)

## 8. API Route and Integration

- [ ] 8.1 Implement `/api/v1/query/api-docs` FastAPI route with `query` and `document_id` parameters
- [ ] 8.2 Implement request/response models using pydantic (`ApiDocQueryRequest`, `ApiDocQueryResponse`)
- [ ] 8.3 Implement ingestion route for DOCX upload that triggers extraction → chunking → indexing pipeline
- [ ] 8.4 Wire ingestion into the existing document processing flow (or as standalone endpoint)
- [ ] 8.5 Implement error handling and logging for the new pipeline

## 9. Testing

- [ ] 9.1 Write unit tests for domain model validation (malformed types, empty strings, missing optional fields)
- [ ] 9.2 Write unit tests for DOCX table parser with synthetic DOCX fixtures (method tables, multi-row functions, property tables)
- [ ] 9.3 Write unit tests for chunk graph builder (parent-child hierarchy, serialization round-trip)
- [ ] 9.4 Write unit tests for hybrid retriever (BM25 scoring, RRF fusion, link traversal depth limiting)
- [ ] 9.5 Write unit tests for DSPy signatures and module (mock LM, verify structured output)
- [ ] 9.6 Write integration test for full pipeline: upload DOCX → chunk → query → verify response has citations
- [ ] 9.7 Write integration test for PDF fallback path
