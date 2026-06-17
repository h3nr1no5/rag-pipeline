## 1. Fix A — Forward strategy parameters to semantic pipeline

- [x] 1.1 In `src/domain/services/processor.py`, modify the `semantic_chunk_pdf()` call at line 189 to pass `min_chunk_size`, `max_chunk_size`, and `overlap` kwargs derived from the strategy's `chunk_size` and `chunk_overlap`:
  - `min_chunk_size = max(50, chunk_size // 4)`
  - `max_chunk_size = chunk_size // 2`
  - `overlap = int(chunk_overlap / chunk_size * 100)` if `chunk_size > 0`, else `10`

## 2. Fix B — Token-count fallback in ChunkAssembler

- [x] 2.1 In `src/pdf_semantic_chunking/chunking/assembler.py`, add a fallback guard in the `assemble()` method after line 64 (after boundary-based segment creation): if `len(segments) <= 2 and len(flat) > 3`, replace segments with output of `_fallback_paragraph_split(flat)`
- [x] 2.2 Implement `_fallback_paragraph_split(self, flat: list[DocumentElement]) -> list[list[DocumentElement]]` that splits elements into segments by accumulated token count targeting `self.max_tokens` per segment
- [x] 2.3 Verify the fallback chunk metadata is reasonable (element_type, section_hierarchy) for non-COM documents

## 3. Fix C — Improve heading detection patterns

- [x] 3.1 In `src/pdf_semantic_chunking/detection/boundaries.py`, extend `HeadingBoundaryDetector.detect()` with:
  - All-caps short line detection (5 < len < 100, fully uppercase, no period): priority 75.0
  - Numbered section header detection (e.g., "1. ", "A)", Roman numerals): priority 85.0
  - Short structural line detection (10 < len < 80, no terminal punctuation): priority 60.0

## 4. Tests

- [x] 4.1 Verify with a real non-COM PDF that semantic chunking now produces multiple chunks (set `engine_type="semantic"`, upload a non-COM PDF, verify chunk_count > 1)
- [x] 4.2 Run existing semantic chunking tests to ensure zero regression for COM-enriched documents
- [x] 4.3 Verify heading detection catches all-caps and numbered headers in a sample PDF
- [ ] 4.4 Verify fallback does NOT activate for COM documents with working boundary detection (>3 segments)
