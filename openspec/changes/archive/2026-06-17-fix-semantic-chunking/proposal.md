## Why

The semantic chunking pipeline is designed for COM API documentation, but when processing non-COM PDFs (e.g., general technical reports, whitepapers), it silently produces 1-2 chunks regardless of document size. The existing "graceful degradation" requirements in the spec are unimplemented. Additionally, strategy parameters (`chunk_size`, `chunk_overlap`) from `ChunkingStrategy` are silently ignored by the semantic pipeline, making configuration non-functional.

## What Changes

- **Fix A**: Pass `ChunkingStrategy` parameters (`chunk_size`, `chunk_overlap`) from the document processor to the semantic pipeline's `ChunkAssembler`, mapping them to `min_chunk_size`/`max_chunk_size`/`overlap`. Strategy config now actually controls chunk sizes.
- **Fix B**: Add a fallback mechanism in `ChunkAssembler.assemble()` — when semantic boundary detection produces ≤2 segments from >3 elements, fall back to token-count-based paragraph splitting that respects `max_chunk_size`. This ensures non-COM documents get chunked into multiple pieces.
- **Fix C**: Improve `HeadingBoundaryDetector` to recognize all-caps lines, numbered section headers ("1.", "1.1", "A."), and short lines without terminal punctuation, making heading detection work on a wider range of PDF layouts.

No breaking changes. The pipeline continues unchanged for COM-enriched documents where boundary detection works correctly.

## Capabilities

### New Capabilities
*(none)*

### Modified Capabilities
- `semantic-chunking-engine`: The graceful degradation scenarios (Requirement 6: "Graceful degradation on poorly structured input", lines 179–191) are currently not implemented. This change makes them operational by:
  - Passing strategy `chunk_size`/`chunk_overlap` into the pipeline so config controls output
  - Adding a token-count fallback split when semantic boundary detection produces too few segments
  - Improving heading detection coverage for non-COM heading patterns

## Impact

| Area | Impact |
|------|--------|
| `src/domain/services/processor.py` | Line 189 — add kwargs to `semantic_chunk_pdf()` call |
| `src/pdf_semantic_chunking/chunking/assembler.py` | Add fallback split method + guard in `assemble()` |
| `src/pdf_semantic_chunking/detection/boundaries.py` | Extend `HeadingBoundaryDetector.detect()` patterns |
| Tests | Update existing tests to cover fallback path and new heading patterns |
