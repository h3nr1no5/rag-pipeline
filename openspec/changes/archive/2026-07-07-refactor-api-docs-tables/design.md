## Context

The API Docs DOCX pipeline at `src/domain/rag/api_docs/extraction/` has 5 stages: parse → detect → convert → chunk → index. The current table detection (`table_detector.py`) and converter (`converter.py`) were built for a generic case where tables have keyword column headers (e.g., "Type", "Name", "Description"). Real-world COM API docs from AxisVM use a different structure:

- Tables have **no headers** — columns are positional
- Each table's **type** (method, property, enum, etc.) is identified by a **bold paragraph** immediately before it ("Functions", "Properties", etc.)
- Tables use consistent column layouts per type, but cells combine name+description in a single column for properties
- The converter's `method_table` config (`{return_type_col, name_col}`) is never read by the extraction code — it's dead configuration

The pipeline does produce correct output on the AxisVM snippet (confirmed by existing E2E tests), but only because the multi-signal keyword fallback happens to work for this document. The approach is fragile — small formatting changes in future DOCX files could break detection entirely.

## Goals / Non-Goals

**Goals:**
- Replace fragile keyword-based detection with robust paragraph-based detection
- Implement per-type positional column extractors mirroring the actual table layouts
- Handle the DOCX table-split edge case (consecutive tables with no intervening paragraph)
- Properly split property name from description when both live in the same cell
- Capture interface descriptions from paragraphs following interface headings
- Remove dead `method_table` config from `config/strategies.yaml` and `DocumentConverter`

**Non-Goals:**
- Changes to the chunk graph builder, text formatter, or indexing stages
- Changes to the PDF pipeline (`com-structure-enrichment`)
- Changes to BM25/embedding tokenization or query behavior
- Full validation on every possible COM DOCX variant (will iterate)
- DOM-level table structure changes in `RawTable` data model

## Decisions

### Decision 1: Paragraph-based detection as primary, keyword fallback as secondary

**Choice**: Walk backwards from each table in the DOCX body to find the nearest preceding bold paragraph. Match its text (lowercased) against a known label map:

```python
TABLE_LABELS = {
    "functions": "method",
    "properties": "property",
    "enumerated types": "enum",
    "error codes": "error_code",
    "records / structures": "record",
}
```

If matched → use that type. If not matched → check if previous sibling was a table → inherit its type. If still unknown → fall back to existing keyword header matching.

**Rationale**: The real document shows these labels are always bold Default paragraphs immediately before tables. Keyword matching has no signal when there are no headers. Paragraph matching is deterministic and directly reflects document structure.

**Alternatives considered**: (a) Content-based heuristics (check for return types, `= value` patterns, `enum` keyword in table text) — more complex, less reliable, harder to debug. (b) ML classification — massive overkill for 5 fixed labels.

### Decision 2: Per-type positional extractors

**Choice**: Separate converter methods for each type, each knowing its column layout:

| Type | Col 0 | Col 1 | Col 2 |
|------|-------|-------|-------|
| method | return_type | name(`params`) or param_name or func_desc | param_desc |
| property | type | name+desc (combined) | — |
| record | field_type | field_name | field_desc |
| enum | — / "enum" | `name = value` or `{` `}` | desc |
| error_code | — / "enum" | `name = value` | desc |

**Rationale**: Each type has a fundamentally different column pattern. A unified generic extractor would require type-specific branching anyway, making it harder to read and maintain.

**Method extractor logic**:
1. Non-empty col 0 → start new function with `return_type`
2. Col 1 contains `(` → parse name (before `(`) and inline params (inside `()`, comma-separated `[modifier] type name`)
3. Col 1 empty + col 2 has text → potentially param desc or func desc
4. Subsequent rows with empty col 0: if col 1 matches a known param name → param description row; else → function description text
5. Fully empty row → function separator

**Property extractor heuristic** (for splitting combined name+desc):
1. Split on ` • ` (bullet with spaces) → name before, desc after
2. Split on ` [` → name before, param+desc after `]`
3. Fallback: find first lowercase→uppercase transition at a word boundary → split there
4. Last resort: entire text is the name, desc is empty

**Positional data rows**: The positional extractors treat `table.headers` as the first data row, so all rows (including what the parser calls "headers") are available for extraction. This is necessary because the actual tables have no header row.

### Decision 3: Config — remove dead `method_table` settings

**Choice**: Delete `method_table: {return_type_col: 0, name_col: 1}` from `config/strategies.yaml` and remove the `self.method_table` attribute from `DocumentConverter`. Column positions are hardcoded per type in each positional extractor. The keyword fallback path also uses hardcoded positions (col 0 = return type, col 1 = name).

**Rationale**: The config was never consumed by `_convert_method_table` — `_find_column(headers, _NAME_KW)` was used instead, which searches header text for keywords like "name", "method", "function". Removing it eliminates dead configuration surface. If future documents need configurable positions, they can be added back when a concrete need arises (YAGNI).

**Risk**: Low. The only code that reads `self.method_table` is `_apply_config()`, which logs that it was updated. No extraction logic references the values.

### Decision 4: Interface description capture

**Choice**: When a Heading 2 or Heading 3 paragraph matches an interface name pattern (starts with `I`, PascalCase), the next non-table paragraph becomes its description — stored on `APIInterface.description`.

**Rationale**: The document consistently puts the description right after the heading and before the first section label. Currently this paragraph is parsed as an orphan. Capturing it enriches the chunk graph with interface-level context.

### Decision 5: Consecutive table inheritance

**Choice**: In `table_detector.py`, when iterating DOCX body children in order, track the last-seen table type. If a table appears and there's a preceding element that was also a table (no paragraph between), inherit the last type.

**Rationale**: The AxisVM document has two consecutive function tables (Tables 130 and 133) with no paragraph between — a DOCX rendering artifact. Without inheritance, the second table would fall through to keyword matching and likely misclassify.

## Risks / Trade-offs

- **[Risk] Property name splitting may produce incorrect extractions** for uncommon patterns (e.g., names ending in lowercase immediately followed by uppercase description). → **Mitigation**: The heuristic degrades gracefully — even a wrong split keeps the full text retrievable since both name and description remain in the chunk. Monitor and iterate as new documents reveal patterns.

- **[Risk] Existing unit tests construct `RawTable` manually with keyword headers** and test the converter directly. The refactored converter won't match the `RawTable` pattern these tests expect. → **Mitigation**: Rewrite test fixtures to use the domain-object output format, testing the full detect→convert path inline where possible. Use representative tables from the real snippet as fixtures.

- **[Risk] Paragraph detection depends on exact label spelling** ("Records / structures", not "Records/structures" or "Records and structures"). → **Mitigation**: Normalize whitespace before matching. Use exact matching after normalization (avoid substring matching to prevent false positives). Add extensibility point for future labels.

- **[Trade-off] Keeping the keyword fallback adds maintenance surface**: but it's small, well-understood, and provides safety for non-standard documents.
