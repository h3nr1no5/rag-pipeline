# Semantic Chunking Engine

## Purpose

Produce semantically coherent chunks from a PDF document's structured element tree (optionally enriched with COM domain metadata) by detecting natural boundaries at function, interface, section, and code-block boundaries, assembling chunks with configurable per-element-type size constraints and overlap, attaching rich hierarchical metadata, and exposing the pipeline via both CLI and async Python API.

## Requirements

### Requirement: Detect semantic chunk boundaries from document structure

The system SHALL identify semantically meaningful chunk boundaries by analyzing the document element tree produced by the structure parser (optionally enriched by the COM structure enrichment stage), using rule-based heuristics to find natural split points at function, method, interface, class, and section boundaries.

#### Scenario: Apply COM-specific boundary priority order
- **WHEN** the document element tree has been enriched by the COM structure enrichment stage and contains elements with `com_type` classifications
- **THEN** the system SHALL prioritize chunk boundaries in this order:
  1. Single function/method (highest value, most queried)
  2. Single property (simple but important)
  3. Enum definition (whole `enum E... { }` block, atomic)
  4. Record/struct definition (atomic)
  5. Error code group (often queried together)
  6. Small related group (fallback for very short adjacent items)
- **AND** SHALL NOT split a function signature + its parameter descriptions + return value
- **AND** SHALL NOT split an entire enum `{ }` block
- **AND** SHALL NOT split a record definition

#### Scenario: Split at major section heading boundaries
- **WHEN** the document element tree contains an H1 or H2 heading element
- **THEN** the system SHALL mark the position immediately before the heading as a hard chunk boundary
- **AND** the heading SHALL be the first element of the new chunk

#### Scenario: Split at function/method signature boundaries
- **WHEN** the document element tree contains a code block or text element matching a function or method signature pattern
- **THEN** the system SHALL mark the position before the signature as a chunk boundary
- **AND** the signature SHALL be the first element of the new chunk

#### Scenario: Recognize C# COM interop patterns as boundaries
- **WHEN** a text element matches C# COM interop patterns (e.g., `interface I\w+`, `\[ComImport\]`, `\[Guid\(`, `\[InterfaceType\(`, `\[DllImport\(`, return type keywords `long`, `void`, `ELongBoolean`, `int`, `bool`, `double`, `string` followed by a method signature like `\b\w+\s+\w+\(`)
- **THEN** the system SHALL mark a boundary before the interface/method definition
- **AND** SHALL set `element_type: "com_interface"` or `element_type: "com_method"` in chunk metadata

#### Scenario: Recognize generic programming language signatures
- **WHEN** a text element matches patterns like `def `, `function `, `class `, `void \w+\(`, `int \w+\(`, `String \w+\(`, `public|private|protected `, or `=>`
- **THEN** the system SHALL mark a boundary before the definition
- **AND** SHALL set `element_type: "function"` or `element_type: "class"` in chunk metadata

#### Scenario: Classify chunk element type from COM enrichment metadata
- **WHEN** the COM structure enrichment stage has classified an element with a `com_type` (e.g., `com_method`, `com_property`, `com_enum`, `com_record`, `com_error_code`)
- **THEN** the system SHALL map `com_type` to the corresponding `element_type` in chunk metadata:
  - `com_method` → `element_type: "function"`
  - `com_property` → `element_type: "property"`
  - `com_enum` → `element_type: "enum"`
  - `com_record` → `element_type: "record"`
  - `com_error_code` → `element_type: "error_code"`
- **AND** SHALL propagate all enrichment metadata (element_name, signature, return_type, parameters, error_codes, keywords) into the chunk's metadata

#### Scenario: Inherit interface context from enrichment hierarchy
- **WHEN** a chunk's element is a child of a `com_interface` in the enrichment tree
- **THEN** the chunk metadata SHALL include the parent interface name as `interface: "IAxisVMApplication"`
- **AND** the section within the interface as `section: "Functions"` (or Properties, Enumerated types, Error codes, Records / structures)

#### Scenario: Split at page boundaries only when semantically meaningful
- **WHEN** a page break occurs mid-paragraph or mid-code-block
- **THEN** the system SHALL NOT split at the page boundary
- **AND** SHALL continue the current element across pages
- **WHEN** a page break occurs after a complete section or at a blank page
- **THEN** the system SHALL mark a soft boundary that may be promoted to hard if the resulting chunk meets size constraints

#### Scenario: Preserve code-description cohesion with point-based threshold
- **WHEN** a code block is immediately preceded by a descriptive paragraph (vertical distance < 50 points in the pdfminer coordinate system — approximately 3 lines of body text at 12pt)
- **THEN** the system SHALL include both the description and code block in the same chunk
- **AND** SHALL merge them even if it exceeds a soft size limit (up to 1.5x max_chunk_size)
- **AND** SHALL NOT merge beyond a hard limit of 2x max_chunk_size, even with cohesion — at that point, split at the paragraph-code boundary

### Requirement: Assemble chunks with configurable size and overlap constraints

The system SHALL assemble final chunks from the bounded segments, enforcing configurable minimum and maximum chunk sizes (in tokens), overlap between adjacent chunks, and merging of undersized adjacent segments. Sizing defaults SHALL vary by element type for COM-enriched documents.

#### Scenario: Apply per-element-type token-based size defaults for COM chunks
- **WHEN** a chunk's `element_type` is known and the document has COM enrichment
- **THEN** the system SHALL apply these token-based size targets:
  | Element Type | Max Tokens (approx) | Rationale |
  |---|---|----|
  | function | 400-800 | Self-contained, high retrieval value |
  | property | 150-400 | Simple but important |
  | enum | 300-600 | Atomic reference |
  | record | 200-500 | Atomic reference |
  | error_code | 200-400 | Often queried together |
  | mixed/fallback | < 600 | Only when no COM-specific type applies |
- **AND** token count SHALL be computed using the same tokenizer as the embedding model (e.g., `cl100k_base` for `text-embedding-3-large`)

#### Scenario: Never split atomic COM constructs
- **WHEN** a bounded segment contains a complete COM construct (function signature + parameter descriptions + return value)
- **THEN** the system SHALL NOT split it, even if it exceeds the per-element-type token target
- **WHEN** a bounded segment contains an entire `enum { ... }` block
- **THEN** the system SHALL NOT split it
- **WHEN** a bounded segment contains a complete record/struct definition
- **THEN** the system SHALL NOT split it
- **AND** the hard maximum for atomic constructs SHALL be 2x the per-element-type token target — beyond that, log a warning and split at the outermost structural boundary

#### Scenario: Merge undersized adjacent chunks
- **WHEN** two adjacent bounded segments are each smaller than `min_chunk_size` (default: 200 tokens)
- **THEN** the system SHALL merge them into a single chunk
- **AND** SHALL concatenate their content with a double newline separator

#### Scenario: Enforce maximum chunk size
- **WHEN** a bounded segment exceeds its per-element-type token target (or default `max_chunk_size` of 800 tokens for untyped segments)
- **THEN** the system SHALL recursively split it at the next available structural boundary (subheading, paragraph break, line break)
- **AND** SHALL NOT split mid-sentence or mid-code-line

#### Scenario: Apply overlap between chunks
- **WHEN** `chunk_overlap` is set to a positive value (default: 10-15% of max_tokens)
- **THEN** the system SHALL append the last `chunk_overlap` tokens of chunk N to the beginning of chunk N+1
- **AND** the overlap SHALL NOT cross a hard boundary (heading, function signature, enum block)
- **AND** for COM chunks, the overlap SHALL include the interface header or introduction context (1-2 sentences) when relevant

### Requirement: Attach rich hierarchical metadata to each chunk

Each output chunk SHALL include a metadata dictionary with the chunk's position in the document hierarchy, source page range, element type, confidence score, and — for COM-enriched chunks — the full COM metadata schema.

#### Scenario: Metadata includes section hierarchy
- **WHEN** a chunk is assembled from a subsection of a document
- **THEN** the metadata SHALL include a `section_hierarchy` array listing all ancestor headings from root to leaf (e.g., `["API Reference", "IComInterface", "Methods", "QueryInterface"]`)
- **AND** SHALL include a `page_range` showing `[start_page, end_page]`

#### Scenario: Metadata includes element type and confidence
- **WHEN** a chunk is created from a detected code block
- **THEN** the metadata SHALL include `element_type: "code_block"` and `confidence: <0.0-1.0>`
- **WHEN** a chunk is created from mixed content (description + code)
- **THEN** the metadata SHALL include `element_type: "mixed"` and list the constituent types

#### Scenario: COM-enriched chunks include full COM metadata schema
- **WHEN** a chunk originates from a COM-enriched element
- **THEN** the metadata SHALL include all of these fields:
  | Field | Type | Example |
  |-------|------|---------|
  | `chunk_id` | uuid-v4 | `"a1b2c3d4-..."` |
  | `source_document` | string | `"axisvm_com_18100_9-45.pdf"` |
  | `page` | int | `9` |
  | `interface` | string | `"IAxisVMApplication"` |
  | `section` | string enum | `"Functions"`, `"Properties"`, `"Enumerated types"`, `"Error codes"`, `"Records / structures"` |
  | `element_type` | string enum | `"function"`, `"property"`, `"enum"`, `"record"`, `"error_code"`, `"note"` |
  | `element_name` | string | `"BringToFront"` |
  | `signature` | string | `"long BringToFront()"` |
  | `return_type` | string | `"long"` |
  | `parameters` | array | `[{name, direction, type, description}]` |
  | `error_codes` | array | `["errJSONpropertyMissing"]` |
  | `has_code_block` | bool | `true` |
  | `token_count` | int | `512` |
  | `parent_chunk_id` | string\|null | `null` |
  | `keywords` | array | `["bring to front", "window", "main form"]` |
  | `created_at` | datetime | `"2026-06-13T..."` |
- **AND** every COM-enriched chunk SHALL have non-empty `interface`, `element_type`, `element_name`, and `signature` (or equivalent for non-function types)
- **AND** function chunks SHALL contain the word "Returns" or "return" in their content or metadata

#### Scenario: Metadata is JSON-serializable
- **WHEN** any chunk metadata is serialized to JSON
- **THEN** it SHALL produce valid JSON with no circular references
- **AND** SHALL be compatible with the existing `Chunk.chunk_metadata` JSON column in the database

### Requirement: Expose both CLI and async Python API

The system SHALL expose the chunking pipeline via two entry points: a CLI for standalone usage and an async Python API for programmatic integration.

#### Scenario: CLI accepts file path and outputs JSONL
- **WHEN** the CLI is invoked as `python -m src.pdf_semantic_chunking.cli input.pdf`
- **THEN** it SHALL output one JSON object per chunk (JSONL format) to stdout
- **AND** SHALL return a non-zero exit code on failure

#### Scenario: CLI supports configurable parameters
- **WHEN** the CLI is invoked with `--min-chunk-size`, `--max-chunk-size`, or `--overlap` flags
- **THEN** the system SHALL use these values instead of defaults
- **AND** unsupported flags SHALL produce a clear usage error

#### Scenario: Async API accepts file path and returns chunk list
- **WHEN** `chunk_pdf("/path/to/doc.pdf")` is called from Python
- **THEN** it SHALL return a list of chunk dicts with `content` and `metadata` keys
- **AND** SHALL run the parsing in a thread executor to avoid blocking the event loop

### Requirement: Graceful degradation on poorly structured input

The system SHALL handle PDFs with minimal or ambiguous structure (no clear headings, single font throughout, unstructured prose) by falling back to paragraph-level boundary detection with appropriate confidence scoring.

#### Scenario: Fall back to paragraph boundaries for prose-only PDF
- **WHEN** a PDF has uniform font usage and no detectable headings, code blocks, or tables
- **THEN** the system SHALL use paragraph breaks (blank lines / double newlines in the layout model) as primary chunk boundaries
- **AND** SHALL set `confidence: "low"` and `fallback_reason: "no_structure_detected"` in metadata

#### Scenario: Fully unstructured text splits by size only
- **WHEN** a PDF has no detectable structure and no paragraph breaks
- **THEN** the system SHALL split by `max_chunk_size` with overlap
- **AND** SHALL set `element_type: "fallback_text"` and `confidence: 0.0`

### Requirement: Configurable hyperlink handling via `use_hyperlinks`

The `ChunkingStrategy` SHALL expose a `use_hyperlinks` boolean configuration that controls whether hyperlinks are considered during document processing and query-time retrieval. When disabled, the entire hyperlink pipeline (extraction, resolution, embedding augmentation, and query-time traversal) SHALL be skipped.

#### Scenario: Default is disabled

- **WHEN** a new `ChunkingStrategy` is created without specifying `use_hyperlinks`
- **THEN** the system SHALL default `use_hyperlinks` to `false`

#### Scenario: Disabled hyperlinks skip link extraction

- **WHEN** a document is processed with a strategy where `use_hyperlinks=false`
- **THEN** the system SHALL NOT call `extract_links()` on the document parser
- **AND** SHALL NOT call `resolve_links()` on the chunk data
- **AND** chunks SHALL NOT have `links` or `backlinks` metadata populated

#### Scenario: Disabled hyperlinks skip link-aware embedding augmentation

- **WHEN** a chunk's embedding is computed and the strategy has `use_hyperlinks=false`
- **THEN** the system SHALL use `build_augmented_text()` (COM prefix, section hierarchy, element type) for embedding
- **AND** SHALL NOT call `build_augmented_text_with_links()`
- **AND** no "Links To:" or "Referenced From:" context SHALL be injected into the embedding text

#### Scenario: Disabled hyperlinks force query-time traversal off

- **WHEN** a query targets documents whose strategy has `use_hyperlinks=false`
- **THEN** the system SHALL force `link_decay_factor=0` for the query, regardless of the request parameter
- **AND** SHALL NOT expand retrieval results via link traversal

#### Scenario: Enabled hyperlinks use current behavior

- **WHEN** a document is processed with a strategy where `use_hyperlinks=true`
- **THEN** the system SHALL extract links, resolve them to chunks, include link context in embedding augmentation, and perform query-time link traversal per the existing requirements in the Link Extraction and Link Traversal specs

### Requirement: Embedding augmentation via metadata prefix

The system SHALL support augmenting chunk content before embedding by prepending a domain-specific prefix, to improve retrieval relevance without altering stored chunk content. For COM-enriched chunks, the prefix SHALL include the element type, interface, and element name for optimal retrieval. The prefix SHALL include resolved link target summaries only when the strategy has `use_hyperlinks=true` and link metadata is available.

#### Scenario: Augment COM-enriched chunks with domain-specific prefix
- **WHEN** a chunk has COM enrichment metadata (interface, element_type, element_name)
- **THEN** the embedder SHALL receive a domain-specific prefix:
  - For functions: `"COM API Function: {interface}.{element_name}"`
  - For properties: `"COM API Property: {interface}.{element_name}"`
  - For enums: `"COM API Enum: {element_name}"`
  - For records: `"COM API Record: {element_name}"`
  - For error codes: `"COM API Error Code: {interface}"`
- **AND** the original content in the database SHALL remain unaltered
- **AND** only the augmented version SHALL be used for embedding computation
- **AND** the augmented text SHALL be:
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

#### Scenario: Augment non-COM chunks with generic section hierarchy
- **WHEN** a chunk does not have COM enrichment but has a non-empty `section_hierarchy`
- **THEN** the embedder SHALL receive: `"[Section: <hierarchy joined by ' > '>]\n<original content>"`
- **AND** the original content SHALL remain unaltered

#### Scenario: Augment with element type when no hierarchy exists
- **WHEN** a chunk has no COM enrichment and empty `section_hierarchy` but a non-empty `element_type`
- **THEN** the embedder SHALL receive: `"[{element_type}]\n<original content>"`
- **WHEN** both hierarchy and type are empty
- **THEN** the original content SHALL be embedded as-is, without prefix

#### Scenario: Augment with link context when link metadata is present and hyperlinks are enabled

- **WHEN** a chunk has non-empty `links` or `backlinks` in `chunk_metadata`
- **AND** the document's strategy has `use_hyperlinks=true`
- **THEN** the augmented text SHALL additionally include a link context block appended after the existing prefix and before the original content, formatted as:
  ```
  Links To:
  - <summary of target chunk content> (type: internal|external)

  Referenced From:
  - <summary of source chunk content>
  ```
- **AND** each link target summary SHALL be limited to 150 characters
- **AND** the augmentation SHALL cap at 3 outgoing links and 3 backlinks (whichever is fewer, most relevant first)
- **AND** SHALL skip external URIs (they have no chunk content to summarize)
- **AND** the original chunk content in the database SHALL remain unaltered
- **AND** only the augmented version SHALL be used for embedding computation
- **WHEN** a chunk has non-empty `links` or `backlinks` but the strategy has `use_hyperlinks=false`
- **THEN** the augmented text SHALL NOT include link context
- **AND** SHALL use the standard `build_augmented_text()` behavior

#### Scenario: Graceful degradation when link target chunks are missing

- **WHEN** a link's `target_chunk_ids` references a chunk ID that no longer exists in the database
- **AND** `use_hyperlinks=true`
- **THEN** the augmentation SHALL include the text `"[deleted chunk]"` as the summary for that link
- **AND** SHALL NOT error or halt augmentation

### Requirement: Processing statistics and diagnostics

The system SHALL report processing statistics after chunking a document, including total input characters, number of chunks produced, detected element types, and per-stage timing.

#### Scenario: CLI reports summary on stderr
- **WHEN** the CLI finishes processing a PDF
- **THEN** it SHALL print a summary line to stderr: `"Processed: X chars → Y chunks (Z types) in T seconds"`
- **AND** SHALL NOT interfere with the JSONL output on stdout

#### Scenario: Async API returns statistics alongside chunks
- **WHEN** `chunk_pdf()` completes successfully
- **THEN** the return value SHALL include both `chunks` and `stats` keys
- **AND** `stats` SHALL contain `total_chars`, `chunk_count`, `element_types` (dict of type→count), and `elapsed_seconds`

#### Scenario: CLI outputs error details on failure
- **WHEN** the pipeline encounters a fatal error during processing
- **THEN** it SHALL output a JSON error report to stderr (not stdout) with keys: `error`, `stage`, `page` (if applicable), `exception`, `context_snapshot`, and `traceback_summary`
- **AND** SHALL exit with a non-zero exit code
- **AND** SHALL NOT produce any partial chunk output on stdout

#### Scenario: Async API returns error report on failure
- **WHEN** `chunk_pdf()` encounters a fatal error
- **THEN** it SHALL raise a typed exception (e.g., `SemanticChunkingError`) containing the structured error report
- **AND** the exception SHALL include all diagnostic fields: `error`, `stage`, `page`, `exception`, `context_snapshot`, `traceback_summary`

### Requirement: Validation and quality gates

The system SHALL include automated and human-driven validation gates to ensure chunk quality meets retrieval targets — every chunk must have required fields, token distribution must be within target ranges, and human sampling must confirm retrieval relevance.

#### Scenario: Automated validation — required fields
- **WHEN** any chunk is produced by the system
- **THEN** the system SHALL verify that `interface` and `element_name` are non-empty for COM-enriched chunks
- **AND** SHALL verify that function chunks contain the word "Returns" or "return" in their content or metadata
- **AND** SHALL verify that no chunk contains page numbers, headers, or footers (strip these during extraction; fail validation if any remain)
- **AND** any chunk failing these checks SHALL be flagged in the processing stats with `validation_warnings: ["missing_field: element_name"]`

#### Scenario: Automated validation — token distribution
- **WHEN** all chunks for a document have been produced
- **THEN** the system SHALL compute token distribution statistics
- **AND** SHALL aim for 80% of COM-enriched chunks to fall within 300-700 tokens for functions, and within their per-element-type targets for other types
- **AND** SHALL report distribution as `token_distribution: {min, max, mean, p50, p90, p95, total}` in processing stats
- **AND** SHALL flag any element type where >20% of chunks exceed the per-element-type max by more than 50%

#### Scenario: Human sampling validation
- **WHEN** a human reviewer validates a set of 20-30 chunks (sampled across element types)
- **THEN** the reviewer SHALL execute realistic queries against the chunk set and verify the top result is correct
- **AND** the reviewer SHALL verify that long compound function names (e.g., `SurfaceSupportForcesByLoadCombinationId`) are retrieved cleanly as a single chunk
- **AND** the reviewer SHALL document any retrieval failures as `sampling_issues` in the validation report

#### Scenario: Validation results reported in processing stats
- **WHEN** validation completes (automated checks)
- **THEN** the `stats` dict returned by `chunk_pdf()` SHALL include:
  ```json
  {
    "validation": {
      "total_chunks": 150,
      "passed": 148,
      "warnings": 2,
      "warnings_detail": ["missing_field: element_name on chunk_42"],
      "token_distribution": {"min": 150, "max": 820, "mean": 412, "p50": 398, "p90": 650, "p95": 780, "total": 61800},
      "element_type_counts": {"function": 80, "property": 30, "enum": 15, "record": 10, "error_code": 15}
    }
  }
  ```
