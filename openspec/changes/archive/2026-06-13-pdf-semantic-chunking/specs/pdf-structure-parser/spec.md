## ADDED Requirements

### Requirement: Parse PDF with layout-aware structure extraction

The system SHALL parse PDF files using a layout-aware parser that extracts not just raw text but the document's structural elements including headings, paragraphs, code blocks, tables, lists, and their spatial positions on each page.

#### Scenario: Extract text with positional data from a standard PDF
- **WHEN** a PDF file with text content is provided
- **THEN** the parser SHALL return a structured representation containing each text element with its bounding box (x0, y0, x1, y1), font name, font size, and page number

#### Scenario: Handle PDF without text layer (scanned document)
- **WHEN** a scanned PDF without an embedded text layer is provided
- **THEN** the parser SHALL raise a clear `PdfStructureError` indicating that text layer extraction is not possible

#### Scenario: Fall back to basic extraction when layout parser fails
- **WHEN** `pdfminer.six` fails to parse the PDF (e.g., encrypted, malformed)
- **THEN** the system SHALL automatically fall back to PyMuPDF (`fitz`) for basic text-only extraction
- **AND** the returned metadata SHALL include a `parser_fallback: true` flag

### Requirement: Infer document hierarchy (headings, sections, subsections)

The system SHALL infer the document's hierarchical structure by analyzing font characteristics (size, weight, family) and spatial position of text elements, producing a section tree with parent-child relationships.

#### Scenario: Detect heading levels from font size and boldness
- **WHEN** a PDF contains text with varying font sizes and bold weights
- **THEN** the system SHALL assign heading levels (H1, H2, H3, body) based on relative font size and weight, with the largest/boldest text at the highest level

#### Scenario: Handle ambiguous heading formatting
- **WHEN** a PDF contains text with font size differences smaller than 1pt between heading levels
- **THEN** the system SHALL assign a lower confidence score (< 0.7) to the heading classification
- **AND** SHALL still include the element in the structure with `confidence: <score>` in metadata

### Requirement: Detect and structure code blocks

The system SHALL detect code blocks within PDF documents by identifying regions of monospace or fixed-width font usage, and optionally by recognizing indented or boxed content regions.

#### Scenario: Detect a monospace font code block
- **WHEN** a PDF contains a contiguous region of text rendered in a monospace font (e.g., Courier, Consolas, mono-spaced)
- **THEN** the system SHALL classify that region as a `code_block` element type
- **AND** SHALL include the entire block as a single extract unit rather than splitting it into individual lines

#### Scenario: Detect a syntactically indented code block (proportional font)
- **WHEN** a PDF contains text in a proportional font but with consistent indentation (4+ spaces) and typical code syntax characters (`{`, `}`, `;`, `->`, `::`)
- **THEN** the system SHALL classify that region as an `inferred_code_block` with confidence < 1.0

### Requirement: Detect and structure tables

The system SHALL detect tabular structures in PDFs by analyzing line art (horizontal/vertical rules) and spatial alignment of text elements into rows and columns.

#### Scenario: Extract a ruled table
- **WHEN** a PDF page contains a table with visible horizontal and vertical rules
- **THEN** the system SHALL extract each cell's text with its row and column index
- **AND** SHALL include a `table` element with `rows` and `columns` metadata

#### Scenario: Extract an alignment-based table (no rules)
- **WHEN** a PDF page contains text arranged in aligned columns without visible rules
- **THEN** the system SHALL infer column boundaries from horizontal alignment
- **AND** SHALL include `inferred_table: true` and a confidence score in metadata

### Requirement: Preserve reading order across multi-column layouts

The system SHALL reconstruct the correct reading order for multi-column PDF layouts, processing text in top-to-bottom, left-to-right column order rather than raw positional order.

#### Scenario: Two-column layout reading order
- **WHEN** a PDF page has a two-column layout
- **THEN** the system SHALL extract text in the correct reading order: complete the left column top-to-bottom, then the right column top-to-bottom
- **AND** SHALL include `column: 0` and `column: 1` metadata on each element

### Requirement: Error handling — full rollback with detailed diagnostic report

The system SHALL handle parsing failures mid-document by performing a full rollback and producing a structured error report, rather than returning partial results.

#### Scenario: Parser failure mid-document triggers full rollback
- **WHEN** the PDF parser encounters a fatal error on any page (e.g., corrupted content stream, unsupported encoding, malformed object)
- **THEN** the system SHALL abort the entire parsing process immediately
- **AND** SHALL NOT return or persist any partially extracted content
- **AND** SHALL return a structured error report containing:
  - `error`: error type name (e.g., `"PdfStructureExtractionError"`)
  - `stage`: the stage that failed (e.g., `"StructureExtractor"`)
  - `page`: the page number where the failure occurred (if applicable)
  - `exception`: the original exception message
  - `context_snapshot`: diagnostic context (file path, total pages, parser type, pages processed before failure)
  - `traceback_summary`: abbreviated traceback for debugging

#### Scenario: CLI error output
- **WHEN** the CLI encounters a parsing failure
- **THEN** it SHALL output the structured error report as JSON to stderr
- **AND** SHALL exit with a non-zero exit code
- **AND** SHALL NOT produce any output on stdout

#### Scenario: No partial results on database rollback
- **WHEN** parsing fails during integration with the main processing pipeline
- **THEN** the document SHALL remain in `status: "error"` with the structured error report in `error_message`
- **AND** no chunks SHALL be persisted for that document

### Requirement: Output a structured element tree consumable by downstream stages

The system SHALL output a tree of `DocumentElement` objects, each with `type` (page, section, heading, paragraph, code_block, table, list, figure), `content`, `metadata` (page, bbox, font info, confidence), and optional `children` list.

#### Scenario: Element tree with hierarchy
- **WHEN** the parser processes a multi-section PDF with headings and body text
- **THEN** each `section` element SHALL contain child elements for its headings and body content
- **AND** the root of the tree SHALL be a `document` element with pages as direct children
