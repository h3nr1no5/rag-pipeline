## Why

`get_heading_level("Heading")` returns `0` (not a heading) when the DOCX paragraph style is the bare `"Heading"` style (no number suffix). This is Word's default level-1 heading, equivalent to `"Heading 1"`. In the Axis COM documentation, the top-level interface sections (e.g., `IAxisVMApplication`) use this bare `"Heading"` style, causing all tables under those sections to be assigned to `"Unknown"` interface in the extracted output.

## What Changes

- **`get_heading_level()` now recognizes bare `"Heading"` style** as level `0` (a new level above `Heading 1`)
- **Non-heading sentinel value changes** from `0` to `-1` to distinguish paragraphs that are actually bare-`Heading` headings (level `0`) from paragraphs that are not headings at all
- **Heading stack filter in converter** updated from `> 0` to `>= 0` to include the new level-0 headings
- **PDF fallback default** updated to use `-1` for consistency
- **Tests** updated to match the new sentinel value and filter

## Capabilities

### New Capabilities

*(None — this is a bug fix within the existing DOCX parsing capability.)*

### Modified Capabilities

*(None — this is an implementation bug fix, not a requirement change. The heading level detection behavior is not specified in existing specs.)*

## Impact

| File | Change |
|------|--------|
| `src/domain/rag/api_docs/extraction/docx_parser.py` | `get_heading_level()`: bare `"Heading"` → `0`; non-heading → `-1`; `RawParagraph.heading_level` default → `-1` |
| `src/domain/rag/api_docs/extraction/converter.py` | Heading stack filter `> 0` → `>= 0` |
| `src/domain/rag/api_docs/extraction/pdf_fallback.py` | Default `heading_level` → `-1` |
| `tests/unit/test_api_docs_extraction.py` | Heading filter `> 0` → `>= 0` |
| `tests/integration/test_api_docs_pdf_fallback.py` | Assert `-1` instead of `0` |
