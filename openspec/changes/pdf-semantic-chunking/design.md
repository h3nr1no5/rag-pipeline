## Context

The existing RAG pipeline processes PDFs by extracting raw text page-by-page via PyMuPDF `fitz` and feeding it into a recursive character/token splitter (`RecursiveChunkingService`). This approach discards all structural information — headings, code blocks, tables, interface signatures, section hierarchy. For technical documentation (COM interfaces, API references, SDK guides), this produces semantically meaningless chunks that hurt retrieval quality: a function signature can be split from its description, a code block separated from its explanation, and interface hierarchies flattened beyond recognition.

This design creates a dedicated **pdf-semantic-chunking** module that **replaces the existing "API Documentation" chunking strategy**. When a user selects this strategy on PDF upload, `processor.py` routes through the semantic pipeline instead of the recursive splitter. The module focuses on three layers:

1. **Structure extraction** — layout-aware PDF parsing (headings, code blocks, tables, reading order)
2. **COM enrichment** — domain-specific identification of COM constructs (interfaces, methods, properties, enums, records, error codes)
3. **Semantic chunking** — atomic boundary detection, per-element-type token sizing, rich metadata, embedding augmentation, validation

**Key constraints:**
- Must produce output compatible with the existing chunk schema (content + chunk_index + metadata)
- Must be embeddable — usable both as a CLI tool and as an async library call
- Quality is prioritized over raw speed — pdfminer parsing may be slower but produces better chunks
- COM enrichment is AxisVM-first but designed for extensibility — non-COM PDFs get graceful degradation
- Must wire into `processor.py` when the "API Documentation" strategy (`is_api_aware=True`) is active

## Goals / Non-Goals

**Goals:**
- Extract PDF text with layout/structure awareness (headings, code blocks, tables, reading order)
- Enrich the extracted structure with COM-specific semantics: interfaces, methods, properties, enums, records, error codes
- Detect semantic boundaries at function, method, interface, property, enum, record, and error code granularity — with COM-specific priority order
- Produce chunks with per-element-type token-based sizing (functions 400-800t, properties 150-400t, enums 300-600t, records 200-500t, error codes 200-400t)
- Attach rich COM metadata per chunk: interface, section, element_type, element_name, signature, return_type, parameters, error_codes, keywords, token_count
- Apply domain-specific embedding prefix (`"COM API Function: IAxisVMApplication.BringToFront"`) to augment retrieval
- Validate chunk quality via automated checks (required fields, token distribution) and human sampling
- Replace the existing "API Documentation" chunking strategy with structure-aware chunking
- Expose a clean async API that the main pipeline (`processor.py`) integrates with directly
- On partial failure, perform full rollback with a detailed structured error report

**Non-Goals:**
- Not a generic catch-all chunker for all PDF types — targets structured technical documentation where strategy is selected as "API Documentation"
- COM enrichment is AxisVM-first v1; other COM dialects or programming languages are future scope
- Not changing the database schema or vector store
- Not adding new API routes or frontend features
- Not handling scanned PDFs or OCR (assumes text-layer PDFs)

## Decisions

### Decision 1: Layout-aware PDF parsing via `pdfminer.six` (with fallback to `fitz`)

**Choice:** Use `pdfminer.six` as the primary parser for structure-aware extraction, with `fitz` (PyMuPDF) as a fallback for standard text extraction when layout analysis isn't needed.

**Rationale:**
- `pdfminer.six` provides LTModel (LTPage, LTFigure, LTTextBox, LTLine, etc.) — a full document object model with positional data for every text element
- This enables extraction of reading order, column detection, heading level inference (via font size/weight/position), code block detection (via monospace font detection), and table structure
- `fitz` is faster but provides no layout model — just raw text and rough bounding boxes
- Fallback to `fitz` when `pdfminer` fails (encrypted PDFs, unusual encodings) ensures robustness

**Alternatives considered:**
- `PyMuPDF` with `get_text("dict")` — provides bounding boxes but no layout model; reading order reconstruction and heading inference would need custom heuristics
- `pypdf` — lightweight but minimal layout support
- `pdfplumber` — good for tables, less suitable for general structure extraction
- `unstructured.io` — powerful but heavy dependency; overkill for this use case

### Decision 2: Rule-based semantic boundary detection (COM priority)

**Choice:** Use a deterministic, rule-based engine for detecting semantic chunk boundaries, with COM-specific priority rules as the primary ordering for enriched documents.

**Rationale:**
- Rule-based detection is predictable, testable, and has zero cold-start latency
- PDF structure patterns for technical docs are regular enough to capture with well-crafted heuristics
- ML-based boundary detection would require labeled data and introduce unpredictability
- Rules can be composed and prioritized, making the system debuggable and extensible

**Boundary priority (for COM-enriched documents):**
1. Single function/method — highest retrieval value, most queried
2. Single property — simple but important
3. Enum definition (whole `enum E... { }` block) — atomic reference
4. Record/struct definition — atomic reference
5. Error code group — often queried together
6. Small related group — fallback for very short adjacent items

**Key heuristics:**
- Heading detection: font size delta + bold + position (from pdfminer LTModel)
- Function/method signature: COM return type keywords (`long`, `void`, `ELongBoolean`, `int`, `bool`, `double`, `string`) + name + parameter list
- C# COM attribute patterns: `[ComImport]`, `[Guid(]`, `[InterfaceType(]`, `[DllImport(]`
- Interface/class markers: `interface I\w+`, `coclass`, `dispinterface`
- Generic patterns: `def `, `function `, `class `, `public|private|protected `, `=>`

**Never-split rules:**
- Function signature + parameter descriptions + return value (atomic)
- Entire `enum { }` block (atomic)
- Record/struct definition (atomic)

**Alternatives considered:**
- `tree-sitter` for parsing code snippets — overkill; detected code blocks are already well-bounded
- ML-based segmentation — too heavy, requires training data

### Decision 2b (NEW): COM structure enrichment as a dedicated pipeline stage

**Choice:** Add a `COM Enricher` stage between structure extraction and boundary detection. This stage walks the generic element tree and produces a COM-aware hierarchy.

**Design:**
```
PDF → Layout Extraction → COM Enrichment [NEW] → Boundary Detection → Chunk Assembly
     (pdfminer)           (identifies interfaces,    (applies COM           (per-element-type
                           classifies elements,       priority rules)        token sizing)
                           extracts params/return)
```

**Enrichment logic:**
1. Detect interface boundaries via attribute cluster + `interface I\w+`
2. Classify each element as `com_method`, `com_property`, `com_enum`, `com_record`, `com_error_code`, or leave unclassified
3. Extract parameter details (name, direction, type, description) from signature + adjacent descriptions
4. Reconstruct multi-line signatures
5. Build hierarchy: Interface → Section (Functions/Properties/Enums/Error codes/Records) → Element
6. Propagate cross-references as metadata (not resolved)

**Non-COM elements:** Unclassified elements pass through with `com_confidence: 0.0` and fall back to generic chunking rules.

**Rationale:**
- Separates concerns: pdfminer doesn't need to know about COM patterns
- The enrichment layer is swappable — future document types (OpenAPI, JavaDoc) can add their own enrichers
- The generic pipeline works without enrichment; enrichment is a quality boost when available

### Decision 3: Rich COM metadata schema (redesigned)

**Choice:** Each chunk carries a metadata dict with a nested `section_hierarchy` array plus the full COM metadata schema for enriched chunks — including typed fields for interface, element_type, element_name, signature, return_type, parameters, error_codes, and keywords.

**Schema for COM-enriched chunks:**
```json
{
  "chunk_id": "uuid-v4",
  "source_document": "axisvm_com_18100_9-45.pdf",
  "page": 9,
  "interface": "IAxisVMApplication",
  "section": "Functions",
  "element_type": "function",
  "element_name": "BringToFront",
  "signature": "long BringToFront()",
  "return_type": "long",
  "parameters": [
    {"name": "CustomID", "direction": "in", "type": "long", "description": "..."}
  ],
  "error_codes": ["errJSONpropertyMissing"],
  "has_code_block": true,
  "token_count": 512,
  "parent_chunk_id": null,
  "keywords": ["bring to front", "window", "main form"],
  "created_at": "2026-06-13T..."
}
```

**Rationale:**
- Flat tags lose parent-child relationships (e.g., knowing a method belongs to which interface)
- Hierarchical metadata enables multi-level filtering at query time ("find functions with `long` return type in `IAxisVMApplication`")
- Compatible with the existing Chunk model's JSON `chunk_metadata` field (no schema migration needed)
- The rich schema enables semantic filtering in vector DB queries (e.g., `filter: interface="IAxisVMApplication" AND element_type="function"`)
- Keywords enable hybrid keyword+vector search even without a dedicated keyword index

### Decision 4: Embedding augmentation via domain-specific prefix

**Choice:** When the semantic chunker is used, the processor augments each chunk's content before embedding by prepending a domain-specific prefix — but stores the original content without the prefix in the database.

**Prefix templates (COM-enriched):**
| Element Type | Prefix Template | Example |
|---|---|---|
| function | `"COM API Function: {interface}.{element_name}"` | `"COM API Function: IAxisVMApplication.BringToFront"` |
| property | `"COM API Property: {interface}.{element_name}"` | `"COM API Property: IAxisVMApplication.ActiveDocument"` |
| enum | `"COM API Enum: {element_name}"` | `"COM API Enum: EMessageDialogButton"` |
| record | `"COM API Record: {element_name}"` | `"COM API Record: RCalculationParameters"` |
| error_code | `"COM API Error Code: {interface}"` | `"COM API Error Code: IAxisVMApplication"` |

**Full augmented text (example):**
```
COM API Function: IAxisVMApplication.BringToFront
Interface: IAxisVMApplication
Section: Functions
Element Type: function
Element Name: BringToFront

long BringToFront()

Bring AxisVM window to front.
Returns 1 if successful, 0 otherwise.
```

**Fallback (non-COM):**
- With section hierarchy: `"[Section: hierarchy > joined > here]\n<content>"`
- With element type only: `"[{element_type}]\n<content>"`
- Neither: embed raw content unchanged

**Implementation:** The augmentation happens in `processor.py` during the embedding step:
```python
if chunk_metadata.get("element_type") in ("function", "property", "enum", "record", "error_code"):
    prefix = f"COM API {element_type.title()}: {interface}.{element_name}"
    augmented = f"{prefix}\nInterface: {interface}\nSection: {section}\nElement Type: {element_type}\nElement Name: {element_name}\n\n{content}"
else:
    augmented = build_augmented_text(content, chunk_metadata)
embedding_vec = await embedder.embed_text(augmented)
# Store original content in DB
```

**Rationale:**
- The domain-specific prefix provides crucial retrieval context that the flat chunk text lacks
- The "COM API Function:" prefix is unique enough to act as a retrieval magnet for API-specific queries
- Augmenting only at embedding time keeps chunks as clean, reusable units in the DB
- No schema changes needed — the original content field is unchanged

### Decision 5: Pipeline architecture with composable stages

**Choice:** Structure the module as a pipeline of composable stages, each implementing a `PipelineStage` protocol:

```python
class PipelineStage(Protocol):
    async def process(self, context: PipelineContext) -> PipelineContext: ...
```

**Stages (amended):**
1. **PDFLoader** — reads PDF bytes, selects parser (pdfminer preferred, fitz fallback)
2. **StructureExtractor** — extracts LTModel and produces a hierarchy of `DocumentElement` objects (Page, Section, CodeBlock, Table, Paragraph, etc.)
3. **COMEnricher** — walks the element tree, identifies COM constructs, classifies elements, extracts parameters/return types/signatures, builds Interface→Section→Element hierarchy
4. **BoundaryDetector** — walks the enriched element tree and marks semantic chunk boundaries using COM-specific priority rules
5. **ChunkAssembler** — slices at boundary marks, applies per-element-type token-based sizing, handles overlap, enforces size constraints, preserves atomic constructs
6. **MetadataEnricher** — attaches the full COM metadata schema, section hierarchy, page numbers, element types, confidence, keywords

**Rationale:**
- Each stage is independently testable and swappable
- Pipeline context is a simple dataclass — easy to log, debug, and evolve
- New stages (e.g., OCR preprocessor, ML boundary scorer) can be inserted without rewriting

### Decision 6: Package structure under `src/pdf_semantic_chunking/`

```
src/pdf_semantic_chunking/
├── __init__.py
├── pipeline/             # Pipeline orchestration
│   ├── __init__.py
│   ├── context.py        # PipelineContext dataclass
│   ├── stage.py          # PipelineStage protocol
│   └── orchestrator.py   # Stage runner
├── extraction/           # PDF loading + structure extraction
│   ├── __init__.py
│   ├── loader.py         # PDFLoader (pdfminer preferred / fitz fallback)
│   └── model.py          # DocumentElement, PageElement, etc.
├── enrichment/           # COM-specific structure enrichment [NEW]
│   ├── __init__.py
│   ├── enricher.py       # COMEnricher orchestrator
│   ├── interface_detector.py  # Interface boundary detection
│   ├── classifier.py     # Element type classifier (method vs property vs enum vs record vs error_code)
│   ├── parameter_extractor.py  # Parameter detail extraction
│   └── patterns.py       # COM-specific regex patterns
├── detection/            # Boundary detection
│   ├── __init__.py
│   ├── boundaries.py     # BoundaryDetector with COM priority rules
│   ├── heuristics.py     # Heading, function, code-block detectors
│   └── patterns.py       # Regex patterns for COM / general tech docs
├── chunking/             # Chunk assembly
│   ├── __init__.py
│   ├── assembler.py      # ChunkAssembler (token-based, per-element-type sizing)
│   └── metadata.py       # MetadataEnricher (COM schema + keywords)
├── cli.py                # CLI entrypoint (click or argparse)
└── api.py                # Async API: `async def chunk_pdf(file_path: str) -> dict`

tests/pdf_semantic_chunking/
├── conftest.py
├── test_extraction/
├── test_enrichment/      # NEW: COM enrichment tests
├── test_detection/
├── test_chunking/
├── test_integration/
└── fixtures/             # Sample PDFs including AxisVM-style COM API ref
```

### Decision 7: Integration routing — processor.py bridge

**Choice:** The semantic chunker is invoked from `processor.py` when the document's strategy indicates API documentation mode. Two approaches:

| Approach | Implementation | Pro | Con |
|----------|---------------|-----|-----|
| **A) Strategy-ID check** | `if strategy.id == "api-docs": return await semantic_chunk()` | Zero schema changes, simplest | Brittle hardcoding; custom strategies can't opt in |
| **B) `engine_type` field** | Add `engine_type: str` to `ChunkingStrategy` model (`"recursive"` \| `"semantic"`); check on processing | Clean and extensible — any strategy can opt into semantic mode | Requires DB migration (add column) |

**Decision:** Use approach **B** (`engine_type` field) for clean extensibility. The migration adds a nullable `VARCHAR` column with default `"recursive"`. The system seed sets `engine_type="semantic"` for the "API Documentation" strategy.

**Processor.py routing logic:**
```python
if strategy.engine_type == "semantic":
    from src.pdf_semantic_chunking.api import chunk_pdf
    result = await chunk_pdf(document.file_path)
    # Apply embedding augmentation
    for chunk in result["chunks"]:
        augmented = build_augmented_text(chunk["content"], chunk["metadata"])
        chunk["embedding"] = await embedder.embed_text(augmented)
    # Persist chunks + embeddings
else:
    # Existing recursive chunking path
```

### Decision 8: Error handling — full rollback with detailed report

**Choice:** On any failure during the semantic chunking pipeline (pdfminer error on page N, COM enricher crash, boundary detector failure, etc.), the entire processing attempt for that document is rolled back and a detailed structured error report is returned.

**Design:**
- No partial chunks are persisted to the database — the document remains in `status: "error"` with `processing_step` set to the failed stage
- The error report includes:
  ```json
  {
    "error": "PdfStructureExtractionError",
    "stage": "StructureExtractor",
    "page": 15,
    "exception": "LTAnon: undefined character mapping",
    "context_snapshot": {
      "file_path": ".../uploaded.pdf",
      "total_pages": 100,
      "parser": "pdfminer.six",
      "processed_pages": 14
    },
    "traceback_summary": "File '.../loader.py', line 142, in _extract_page..."
  }
  ```
- The document's `error_message` field stores a JSON-serialized version of this report
- The CLI outputs the error to stderr with a non-zero exit code

**Rationale:**
- Partial results are worse than no results — they produce misleading retrieval
- A detailed error report enables users and developers to diagnose exactly what went wrong without re-running
- The rollback is safe because all DB operations happen in a single transaction at the end of processing

### Decision 9 (NEW): Validation and quality gates

**Choice:** Implement automated validation checks and a human sampling workflow to ensure chunk quality meets retrieval targets.

**Automated checks (run after chunk assembly):**
1. Required fields: every COM-enriched chunk must have non-empty `interface` and `element_name`
2. Content check: function chunks must contain "Returns" or "return" in content or metadata
3. Cleanliness: no chunk may contain page numbers, headers, or footers (strip during extraction; flag if any remain)
4. Token distribution: 80% of COM-enriched chunks should fall within 300-700 tokens for functions, and within per-element-type targets for other types

**Human sampling workflow (recommended on 20-30 chunks):**
1. Execute realistic queries against the chunk set (e.g., "How do I bring AxisVM window to front?")
2. Verify the top-1 retrieval result is the correct chunk
3. Verify long compound function names (e.g., `SurfaceSupportForcesByLoadCombinationId`) are retrieved cleanly as single chunks
4. Document any failures as sampling issues

**Validation reporting:**
```json
{
  "validation": {
    "total_chunks": 150,
    "passed": 148,
    "warnings": ["missing_field: element_name on chunk_42"],
    "token_distribution": {"min": 150, "max": 820, "mean": 412, "p50": 398, "p90": 650, "p95": 780, "total": 61800},
    "element_type_counts": {"function": 80, "property": 30, "enum": 15, "record": 10, "error_code": 15}
  }
}
```

**Rationale:**
- Automated checks catch structural issues early in development
- Token distribution targets prevent degenerate chunking (all tiny chunks or all giant chunks)
- Human sampling validates that the chunking strategy actually works for real queries
- Validation results are machine-readable and can be integrated into CI

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| **pdfminer.six is slower than fitz** (~10-50x on large PDFs) | Accepted — quality is prioritized over speed. Use thread executor to avoid blocking event loop. No speed acceptance criteria; target "correct chunks, even if slow" |
| **COM patterns are AxisVM-specific and may not generalize** to other C# COM interop docs | Pattern registry is extensible; start with AxisVM patterns, add more as needed. Non-COM PDFs get graceful degradation |
| **Heading inference heuristics may misfire** on unusual PDF layouts | Confidence score per element; configurable threshold; easy to add new heuristics |
| **Parameter extraction from PDF is unreliable** when descriptions are far from signatures | Use multiple extraction strategies (bullet list, table, inline prose) with confidence scoring; fall back to signature-only extraction |
| **Token-based sizing depends on tokenizer** — different embedding models give different counts | Tokenizer must match the embedding model; document which tokenizer is used in chunk metadata |
| **Multi-column PDFs still challenging** for reading order reconstruction | pdfminer's LTLayout handles basic cases; add post-processing pass for column reordering |
| **Large PDFs may produce many small chunks** (one per function) | Configurable min_chunk_size to merge tiny adjacent chunks; hard merge limit of 2x max token target |
| **No OCR support** — scanned PDFs return empty text | Explicit error message directing users to OCR preprocessors; not a goal for v1 |
| **pdfminer crashes mid-document** (page 30 of 100) | Full rollback with detailed error report; document stays in `status: "error"` with structured diagnostics; no partial chunks persisted |

## Open Questions

- What is the recommended embedding model for COM API retrieval? `all-MiniLM-L6-v2` (current, 384 dims) vs. `text-embedding-3-large` (256/1024/3072 dims, recommended in spec) vs. `voyage-code-2` (code-aware). Decision deferred — v1 can support configurable models with a documented tradeoff.
- Should the CLI output JSONL (one JSON object per line) or a JSON array? Proposal: JSONL for streaming compatibility, with an optional `--format json` flag for array output.
- How should parameter descriptions stored in bullet lists vs. inline prose vs. tables be handled differently? Proposal: all three patterns should be supported with decreasing confidence (table > list > inline), with the extraction method recorded in metadata.
