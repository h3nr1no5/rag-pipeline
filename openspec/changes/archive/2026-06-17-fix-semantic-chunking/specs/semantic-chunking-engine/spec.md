## ADDED Requirements

### Requirement: Pass chunking strategy parameters to semantic pipeline

The document processor SHALL forward `chunk_size` and `chunk_overlap` from the `ChunkingStrategy` to the semantic pipeline as `min_chunk_size`, `max_chunk_size`, and `overlap` parameters, so that strategy configuration controls semantic chunk output sizes.

#### Scenario: Strategy chunk_size maps to semantic max_chunk_size
- **WHEN** a document is processed with `engine_type="semantic"` and a `ChunkingStrategy` with `chunk_size=500`
- **THEN** the system SHALL call `semantic_chunk_pdf()` with `max_chunk_size=250` (chunk_size ÷ 2)
- **AND** SHALL call with `min_chunk_size=max(50, chunk_size ÷ 4)` (i.e., 125 for chunk_size=500)

#### Scenario: Strategy chunk_overlap maps to overlap percentage
- **WHEN** a document is processed with `engine_type="semantic"` and `ChunkingStrategy.chunk_overlap=50`
- **THEN** the system SHALL derive an overlap percentage from the ratio `(chunk_overlap ÷ chunk_size) × 100`
- **AND** SHALL floor the value at 0 and cap at 50
- **WHEN** `chunk_size=0` (invalid)
- **THEN** SHALL default `overlap=10`

### Requirement: Fall back to token-count split when boundary detection is insufficient

The `ChunkAssembler` SHALL detect when semantic boundary detection produced too few segments and automatically fall back to a token-count-based paragraph split to ensure non-COM documents produce multiple chunks.

#### Scenario: Fewer than 3 segments from more than 3 elements triggers fallback
- **WHEN** boundary-based segmentation produces ≤2 segments from a flat element list with >3 elements
- **THEN** the system SHALL discard the boundary-based segments and re-split using a token-count-based paragraph split
- **AND** each new segment SHALL target `max_chunk_size` tokens (computed as word count via `len(text.split())`)
- **AND** the fallback SHALL NOT activate when boundary detection produced ≥3 segments

#### Scenario: Fallback split creates multiple segments
- **WHEN** a flat element list has 50 elements and `max_chunk_size=250` tokens (≈62 words per element)
- **THEN** the fallback SHALL group elements until each segment reaches ~250 tokens
- **AND** SHALL produce multiple segments (not a single segment containing all elements)
- **AND** each segment SHALL be processed through the same chunk assembly pipeline (metadata building, merging, overlap)

#### Scenario: Fallback preserves per-chunk metadata
- **WHEN** segments are created via fallback token-count split
- **THEN** each resulting chunk SHALL include element_type derived from its constituent elements (default "mixed" for non-COM elements)
- **AND** SHALL include `section_hierarchy` metadata when available
- **AND** SHALL set `confidence` based on content quality (no artificial downgrade for fallback chunks)

### Requirement: Improve heading detection with content-based heuristics

The `HeadingBoundaryDetector` SHALL recognize additional heading patterns beyond pdfminer's `HEADING` element type classification, using content analysis to detect headings in non-COM PDFs.

#### Scenario: Detect all-caps short lines as headings
- **WHEN** an element's content is 5–100 characters, fully uppercase, and has no trailing period
- **THEN** the system SHALL mark a boundary with `boundary_type="heading"` and `priority=75.0`
- **AND** SHALL NOT match if the content is shorter than 6 characters (to avoid single-letter artifacts)

#### Scenario: Detect numbered section headers as headings
- **WHEN** an element's content matches `^[A-Z0-9][\.\)]\s+` (e.g., "1. Introduction", "A) Scope", "2.1 Background")
- **OR** matches Roman numeral pattern `^[IVXLCDM]+\.\s+` (e.g., "II. Section")
- **THEN** the system SHALL mark a boundary with `boundary_type="heading"` and `priority=85.0`

#### Scenario: Detect short structural lines as low-confidence headings
- **WHEN** an element's content is 10–80 characters and does NOT end with sentence-ending punctuation (`.`, `:`, `!`, `?`)
- **THEN** the system SHALL mark a boundary with `boundary_type="heading"` and `priority=60.0`
- **AND** these markers SHALL have lower priority than numbered or all-caps heading markers, so they are overridden at the same element index

#### Scenario: Heading detection coexists with existing COM-based detection
- **WHEN** boundary markers from improved heading detection overlap with COM signature markers at the same element index
- **THEN** COM signature markers (priority 80–100) SHALL take precedence over content-based heading markers (priority 60–85)
- **AND** the existing priority-based deduplication in `BoundaryDetector.detect()` SHALL handle this correctly without modification
