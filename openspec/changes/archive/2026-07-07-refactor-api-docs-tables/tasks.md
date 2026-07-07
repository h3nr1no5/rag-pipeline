## 1. Paragraph-Based Detection

- [x] 1.1 Add `_detect_by_paragraph()` method to `TableDetector` — walk backwards from table index, scan bold paragraphs, match against known labels
- [x] 1.2 Add consecutive-table inheritance logic — if previous DOCX sibling was a table, inherit its type
- [x] 1.3 Reorder detection priority: paragraph match → inheritance → keyword fallback
- [x] 1.4 Add `detect_from_document()` method — takes `RawDocument`, returns `dict[int, str]` mapping table index → type

## 2. Per-Type Positional Converters

- [x] 2.1 Rewrite `_convert_method_table()` — positional extractor with return type from col 0, name+params from col 1, param desc matching, function desc fallback, empty-row separation
- [x] 2.2 Add `_convert_property_table()` — type from col 0, name+desc split heuristic from col 1 (bullet → bracket → word-boundary fallback)
- [x] 2.3 Add `_convert_enum_table()` — parse `EnumName {`, `name = value,`, `}` rows with col 2 descriptions
- [x] 2.4 Add `_convert_error_table()` — identical to enum extractor but maps to error code domain objects
- [x] 2.5 Add `_convert_record_table()` — field type from col 0, name from col 1, desc from col 2, record name from first row
- [x] 2.6 Wire dispatch in `DocumentConverter` — route based on detected table type to the appropriate `_convert_*` method

## 3. Interface Description Capture

- [x] 3.1 Add interface name detection — Heading 2/3 matching `I[A-Z][a-zA-Z0-9]*`
- [x] 3.2 Capture next non-table paragraph as interface description
- [x] 3.3 Store description on `APIInterface.description` in the domain model

## 4. Config Cleanup

- [x] 4.1 Remove `method_table` from `config/strategies.yaml`
- [x] 4.2 Remove `self.method_table` from `DocumentConverter.__init__()` and `_apply_config()`

## 5. DOCX Parser Enhancement

- [x] 5.1 Add `bold: bool` field to `RawParagraph`
- [x] 5.2 Populate `bold` from `para.runs` in `_extract_paragraph()`

## 6. Pipe detection through Manager

- [x] 6.1 Update `ApiDocPipelineManager.ingest_docx()` to use `detect_from_document()` instead of per-table `detect()`

## 7. Unit Test Updates

- [x] 7.1 Update `tests/unit/test_api_docs_extraction.py` — rewrite converter tests to use positional table fixtures (not keyword-headered RawTables), cover all 5 table types
- [x] 7.2 Update `tests/unit/test_converter_config.py` — remove `method_table` config test, align with new dispatch approach
- [x] 7.3 Add paragraph detection tests — mock paragraph stream, verify label matching and inheritance fallback
- [x] 7.4 Add property split heuristic tests — verify bullet, bracket, and word-boundary splitting
- [x] 7.5 Add consecutive table inheritance test — two tables with no paragraph between

## 8. Integration Test Verification

- [x] 8.1 Run existing E2E tests (`test_api_docs_e2e.py`) against real `axis com snippet.docx` — verify queries still return meaningful results
- [x] 8.2 Full pipeline run: lint (`ruff check .`), typecheck (`mypy src/`), unit tests, integration tests

## 9. Main Spec Updates

- [x] 9.1 Update `openspec/specs/api-docs-strategy/spec.md` — replace `method_table` requirement with positional column layout per type
- [x] 9.2 Update `openspec/specs/strategy-yaml-config/spec.md` — remove `method_table` from YAML example, description, and config_schema
