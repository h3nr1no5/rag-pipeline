## 1. Project Scaffolding & Dependencies

- [x] 1.1 Create package directory `src/pdf_semantic_chunking/` with `__init__.py` and subdirectories (`pipeline/`, `extraction/`, `enrichment/`, `detection/`, `chunking/`)
- [x] 1.2 Add `pdfminer.six` dependency to `pyproject.toml`
- [x] 1.3 Create test directory `tests/pdf_semantic_chunking/` with `conftest.py`, `__init__.py`, and subdirectories for each module

## 2. Document Element Model

- [x] 2.1 Define `DocumentElement` dataclass in `extraction/model.py` with fields: `type` (Literal enum), `content` (str), `metadata` (dict), `children` (list[DocumentElement]), `bbox` (tuple), `confidence` (float)
- [x] 2.2 Define element types enum: `PAGE`, `SECTION`, `HEADING`, `PARAGRAPH`, `CODE_BLOCK`, `TABLE`, `LIST`, `FIGURE`, `INFERRED_CODE_BLOCK`, `INFERRED_TABLE`, `FALLBACK_TEXT`
- [x] 2.3 Define `DocumentHierarchy` class as a tree container with root `DocumentElement` and helper methods for traversal, find by type, and flatten to depth-first list

## 3. COM Structure Enrichment

- [x] 3.1 Define `ComDocumentElement` dataclass in `enrichment/model.py` that extends `DocumentElement` with: `com_type` (optional Literal enum), `element_name`, `signature`, `return_type`, `parameters`, `error_codes`, `enum_members`, `record_members`, `keywords`, `com_confidence`
- [x] 3.2 Define COM element types enum: `COM_INTERFACE`, `COM_METHOD`, `COM_PROPERTY`, `COM_ENUM`, `COM_RECORD`, `COM_ERROR_CODE`
- [x] 3.3 Implement `InterfaceDetector` in `enrichment/interface_detector.py` — detects COM interface boundaries by identifying attribute clusters (`[ComImport]`, `[Guid(...)]`, `[InterfaceType(...)]`) followed by `interface I\w+` declarations
- [x] 3.4 Implement `ElementClassifier` in `enrichment/classifier.py` — classifies elements as method vs property vs enum vs record vs error_code using C# COM interop patterns; includes property detection via `get_`/`set_` prefix, `[propget]`/`[propput]` attributes, and `{ get; set; }` syntax
- [x] 3.5 Implement `ParameterExtractor` in `enrichment/parameter_extractor.py` — parses parameter names, types, and direction indicators from signatures (`[in]`, `[out]`, `[in, out]`); associates parameter descriptions from adjacent paragraphs, bullet lists, or tables
- [x] 3.6 Implement signature reconstruction — detects multi-line signatures (return type on one line, name+params on next) by checking indentation and rejoins them
- [x] 3.7 Implement `EnumMemberExtractor` — extracts member names and optional values from `enum E... { }` blocks
- [x] 3.8 Implement `ErrorCodeGrouper` — associates error code constants (e.g., `EApplicationError` members) with their nearest preceding interface
- [x] 3.9 Implement `COMEnricher` orchestrator stage in `enrichment/enricher.py` — runs all enrichment sub-stages, builds Interface → Section → Element hierarchy, handles non-COM elements with graceful degradation (`com_confidence: 0.0`)

## 4. Pipeline Infrastructure

- [x] 4.1 Define `PipelineContext` dataclass in `pipeline/context.py` with fields: `file_path`, `parser_type`, `element_tree`, `enriched_tree` (optional, after COM enrichment), `boundaries`, `chunks`, `stats` (dict), `errors` (list)
- [x] 4.2 Define `PipelineStage` protocol in `pipeline/stage.py` with `async def process(context: PipelineContext) -> PipelineContext`
- [x] 4.3 Implement `PipelineOrchestrator` in `pipeline/orchestrator.py` that accepts a list of stages, runs them sequentially, collects per-stage timing into stats, and handles stage failures — on first error, aborts with structured error report (no graceful degradation at pipeline level)

## 5. PDF Loader & Structure Extraction

- [x] 5.1 Implement `PdfminerParser` in `extraction/loader.py` that wraps `pdfminer.high_level.extract_pages()` and converts LTPage/LTTextBox/LTFigure into `DocumentElement` hierarchy
- [x] 5.2 Implement `FitzFallbackParser` in `extraction/loader.py` that uses `fitz` (PyMuPDF) `get_text("dict")` and produces flat page-level elements with bounding boxes
- [x] 5.3 Implement `PDFLoader` stage that detects parser availability (prefer pdfminer, fall back to fitz), runs parsing in thread executor, and populates `context.element_tree`
- [x] 5.4 Implement heading level inference from font size/weight/position heuristics (compare relative sizes, detect bold, check page-center positioning) — assign H1–H6
- [x] 5.5 Implement code block detection from monospace font regions and syntax-indentation heuristics
- [x] 5.6 Implement table extraction from ruled lines (`pdfminer` LTLine clustering) and alignment-based column inference
- [x] 5.7 Implement multi-column reading order detection using `pdfminer`'s LTLayout grouping, with post-processing for known column patterns (2-column, 3-column)

## 6. Boundary Detection Heuristics

- [x] 6.1 Implement `HeadingBoundaryDetector` — marks boundaries before H1/H2 elements
- [x] 6.2 Implement `FunctionSignatureDetector` — regex-based detection of function/method signatures including C# COM interop patterns (`long`, `void`, `ELongBoolean`, `\[ComImport\]`, `\[Guid\(`, `\[InterfaceType\(`, `\[DllImport\(`, `interface I\w+`) and generic signatures (`def `, `class `, `function `, `public|private|protected `, `=>`)
- [x] 6.3 Implement `CodeBlockBoundaryDetector` — marks boundaries before and after detected code blocks
- [x] 6.4 Implement `TableBoundaryDetector` — marks boundaries before and after table elements
- [x] 6.5 Implement `PatternRegistry` in `detection/patterns.py` — composable registry of regex patterns with priority levels, extensible via config
- [x] 6.6 Implement `BoundaryDetector` orchestrator stage — runs all boundary detectors, applies COM-specific priority order (function > property > enum > record > error code), deduplicates overlapping boundaries, promotes/demotes boundaries based on context (e.g., suppress page-break boundary mid-paragraph)
- [x] 6.7 Implement `ContextPrefixBuilder` — when a COM-enriched chunk boundary is created, include 1-2 sentences of interface introduction context as overlap prefix

## 7. Chunk Assembly & Metadata Enrichment

- [x] 7.1 Implement `ChunkAssembler` stage in `chunking/assembler.py` — slices enriched element tree at boundary marks, applies per-element-type token-based sizing defaults (function 400-800t, property 150-400t, enum 300-600t, record 200-500t, error code 200-400t), handles merge of undersized chunks (< 200 tokens), handles oversized chunks with recursive structural splitting, and applies overlap (10-15% of max tokens)
- [x] 7.2 Ensure `ChunkAssembler` preserves atomic COM constructs — never split a function signature + parameters + return value, never split an `enum { }` block, never split a record definition; hard cap at 2x per-element-type token target with warning log
- [x] 7.3 Ensure `ChunkAssembler` preserves code-description cohesion — preceding description paragraph stays with code block when vertical distance < 50pt in pdfminer coordinates, overriding soft limit up to 1.5x max_tokens, with hard cap at 2x max_tokens
- [x] 7.4 Implement token counting utility — wraps the embedding model's tokenizer (configurable, default `cl100k_base`) for accurate per-chunk token counts
- [x] 7.5 Implement `MetadataEnricher` stage in `chunking/metadata.py` — attaches the full COM metadata schema: `interface`, `section`, `element_type`, `element_name`, `signature`, `return_type`, `parameters`, `error_codes`, `has_code_block`, `token_count`, `parent_chunk_id`, `keywords`, plus generic fields `section_hierarchy`, `page_range`, `confidence`, `fallback_reason`
- [x] 7.6 Implement keyword extraction — auto-extract keywords from `element_name` and description text (split camelCase/PascalCase names, include common query terms)
- [x] 7.7 Implement graceful degradation: no-structure fallback to paragraph boundaries, fully unstructured fallback to size-based split with `confidence: 0.0`

## 8. Validation Gates

- [x] 8.1 Implement `RequiredFieldValidator` — verifies every COM-enriched chunk has non-empty `interface`, `element_type`, `element_name`; verifies function chunks contain "Returns" or "return"; verifies no chunk contains page numbers/headers/footers; flags warnings for any failures
- [x] 8.2 Implement `TokenDistributionAnalyzer` — computes min, max, mean, p50, p90, p95, and total token counts across all chunks; flags element types where >20% of chunks exceed per-type max by >50%
- [x] 8.3 Implement `ValidationReportBuilder` — aggregates all validation results into the `stats.validation` dict returned by `chunk_pdf()`
- [x] 8.4 Implement `HumanSamplingHelper` — exports a representative sample of 20-30 chunks (stratified by element type) for human review, along with suggested realistic queries for retrieval testing

## 9. Entry Points

- [x] 9.1 Implement `cli.py` — `argparse`-based CLI with positional `file_path`, optional `--min-chunk-size`, `--max-chunk-size`, `--overlap`, `--format` (jsonl/json), outputs JSONL to stdout and summary to stderr; on error outputs JSON error report to stderr and exits non-zero
- [x] 9.2 Implement `api.py` with `async def chunk_pdf(file_path: str, **kwargs) -> dict` returning `{"chunks": [...], "stats": {...}}` — runs full pipeline in thread executor; raises `SemanticChunkingError` with structured error report on failure
- [x] 9.3 Add `python -m src.pdf_semantic_chunking` entry point support via `__init__.py` or `__main__.py`

## 10. Processor Integration

- [x] 10.1 Add `engine_type` column to `ChunkingStrategy` DB model (`VARCHAR`, default `"recursive"`, nullable) with Alembic migration
- [x] 10.2 Update system seed in `src/api/main.py` — set `engine_type="semantic"` for the "API Documentation" strategy
- [x] 10.3 Modify `src/domain/services/processor.py` — add routing logic: when `strategy.engine_type == "semantic"`, call `chunk_pdf()` from the semantic module instead of the recursive chunking path
- [x] 10.4 Implement `build_augmented_text(chunk_content, chunk_metadata) -> str` helper — prepends COM-specific prefix (`"COM API Function: Interface.Name"`) for COM-enriched chunks; falls back to generic section hierarchy prefix for non-COM chunks
- [x] 10.5 Wire embedding augmentation into processor.py: after semantic chunking, augment content before calling `embedder.embed_text()`, store original content in DB
- [x] 10.6 Implement error handling in processor.py: catch `SemanticChunkingError`, roll back document transaction, persist structured error report in `document.error_message`, set `status: "error"`
- [x] 10.7 Add/changed in the upload endpoint: allow users to select the "API Documentation" strategy for PDF uploads, validate that semantic strategy is only used with PDF doc_types

## 11. Testing

- [ ] 11.1 Create test fixture PDFs in `tests/pdf_semantic_chunking/fixtures/` — include structured PDF with headings/code/tables, unstructured prose PDF, C# COM interop-style AxisVM API reference PDF (with interfaces, methods, properties, enums, records, error codes), and multi-column layout PDF
- [ ] 11.2 Write unit tests for `extraction/model.py` — element tree creation, traversal, serialization
- [ ] 11.3 Write unit tests for `enrichment/patterns.py` — C# COM interop pattern matching (`long`, `void`, `ELongBoolean`, `[ComImport]`, `[Guid(]`, `[InterfaceType(]`), interface boundary detection, element classification
- [ ] 11.4 Write unit tests for `enrichment/classifier.py` — method vs property vs enum vs record vs error_code classification with various C# COM patterns
- [ ] 11.5 Write unit tests for `enrichment/parameter_extractor.py` — parameter parsing from inline signatures, bullet lists, and tables
- [ ] 11.6 Write unit tests for `detection/patterns.py` — C# COM interop pattern matching, generic function signature matching
- [ ] 11.7 Write unit tests for `detection/heuristics.py` — heading level inference, code block detection (mocked pdfminer output)
- [ ] 11.8 Write unit tests for `chunking/assembler.py` — per-element-type token sizing, merge logic, oversize splitting, overlap application, atomic construct preservation, code-description cohesion with 50pt threshold and 2x hard limit
- [ ] 11.9 Write unit tests for `chunking/metadata.py` — COM metadata schema, section hierarchy building, confidence scoring, keyword extraction
- [ ] 11.10 Write unit tests for `build_augmented_text()` — COM-specific prefix, hierarchy prefix, element type prefix, empty fallback
- [ ] 11.11 Write unit tests for `validation/` — required field validation, token distribution analysis, validation report building
- [ ] 11.12 Write integration tests for the full pipeline using fixture PDFs — verify chunk count, element types, metadata structure, COM enrichment accuracy, and no data loss
- [ ] 11.13 Write CLI integration test — invoke via `subprocess`, verify JSONL output and exit codes; test error mode (corrupt PDF) produces JSON error report on stderr
- [ ] 11.14 Write fallback test — verify graceful degradation when pdfminer is unavailable or fails; verify non-COM PDFs get correct fallback behavior
- [ ] 11.15 Write processor integration test — mock a document with `engine_type="semantic"`, verify routing to semantic chunker and embedding augmentation with COM-specific prefix

## 12. Validation & Documentation

- [ ] 12.1 Run full test suite: `uv run pytest tests/pdf_semantic_chunking/ -v`
- [ ] 12.2 Run lint: `uv run ruff check src/pdf_semantic_chunking/ src/domain/services/processor.py`
- [ ] 12.3 Run type check: `uv run mypy src/pdf_semantic_chunking/ src/domain/services/processor.py`
- [ ] 12.4 Verify all sample PDFs (AI.pdf, axisvm_csharp_api.pdf, axisvm_csharp_guide.pdf) produce meaningful chunks via CLI — particularly verify C# COM interop patterns match the AxisVM API content
- [ ] 12.5 Run validation analysis on AxisVM API PDF output — verify token distribution targets (80% of chunks in 300-700t range), verify all required fields present
- [ ] 12.6 Run human sampling validation — retrieve with realistic queries ("How do I bring AxisVM window to front?", "List all error codes in IAxisVMApplication"), verify top-1 results are correct
- [ ] 12.7 End-to-end test: upload AxisVM API PDF with "API Documentation" strategy via the upload endpoint, verify chunks are created with correct metadata and embeddings
