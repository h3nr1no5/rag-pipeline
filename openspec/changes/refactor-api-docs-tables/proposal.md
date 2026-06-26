## Why

The current DOCX table detection relies on header keyword matching (e.g., looking for `[in]`, `[out]` in column headers), which fails when tables have no headers — as they don't in real COM API docs. The converter also ignores its `method_table` position config, using hardcoded keyword logic instead. This means the pipeline misclassifies tables or misses content entirely on real-world documents like the AxisVM COM spec.

After analyzing the actual `axis com snippet.docx`, the real pattern is clear: tables are preceded by bold section labels ("Functions", "Properties", "Enumerated types", etc.) with positional columns — no headers.

## What Changes

- **Replace** header keyword matching with paragraph-based table type detection, using the bold section label immediately above each table
- **Add** inheritance fallback: consecutive tables with no label between them inherit the previous table's type (handles DOCX table splits)
- **Rewrite** the converter with per-type positional extractors instead of one-size-fits-all keyword matching
- **Add** heuristic splitting for property name+description (combined in one cell)
- **Add** interface description capture (paragraph after interface heading)
- **Remove** unused `method_table` config from `config/strategies.yaml` and from `DocumentConverter` — positions are hardcoded per type in the positional extractors; the keyword fallback path also uses hardcoded positions
- No changes to the chunk graph builder, text formatter, BM25/embedding index, or query pipeline

## Capabilities

### New Capabilities
- `docx-table-detection`: Detects table type from the bold paragraph immediately preceding each table in the DOCX. Supports 5 section labels: "Functions", "Properties", "Enumerated types", "Error codes", "Records / structures". Falls back to inheritance for consecutive tables, then to existing multi-signal keyword matching.
- `docx-table-conversion`: Extracts domain objects from DOCX tables using positional column indices per type — return type in col 0, signature with inline params in col 1, parameter descriptions in col 1+2, property name+description from combined col 1, enum/error code name=value+description pairs from col 1+2, record fields from col 0+1+2.

### Modified Capabilities
- *(None — the extraction pipeline's table handling was not previously spec'd)*

## Impact

- **Files**: `src/domain/rag/api_docs/extraction/table_detector.py` (detection logic), `src/domain/rag/api_docs/extraction/converter.py` (extraction logic), `config/strategies.yaml` (remove dead `method_table` config)
- **Tests**: Unit tests in `tests/unit/test_api_docs_extraction.py` and `tests/unit/test_converter_config.py` use manual `RawTable` objects with keyword headers — need updating to reflect positional/paragraph-based path
- **Dependencies**: `python-docx` (already used), no new dependencies
