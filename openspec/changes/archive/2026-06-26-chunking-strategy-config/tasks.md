## 1. Foundation — YAML config file and DB migration

- [x] 1.1 Create `config/` directory and `config/strategies.yaml` with seed definitions for recursive, semantic, and api-docs strategies — exact concrete values (params, type_patterns, heading_policy, method_table, formatting) are specified in `design.md` under "Concrete YAML values"
- [x] 1.2 Add nullable `config` JSON column to `ChunkingStrategy` DB model (`src/infrastructure/database/models.py`) — use `JSON` type from SQLAlchemy, nullable=True, default=None
- [x] 1.3 Add `config: dict | None` field to Pydantic response/update schemas in `src/api/schemas/document.py` (`ChunkingStrategyResponse`, `ChunkingStrategyUpdate`)

## 2. YAML seeding — replace hardcoded lifespan logic

- [x] 2.1 Add PyYAML to project dependencies (`pyproject.toml`)
- [x] 2.2 Create `src/infrastructure/strategies/seeder.py` with:
  - `load_strategies_from_yaml(path: str) -> dict` — reads YAML, validates structure, returns dict
  - `apply_config_overrides(settings, yaml_strategies)` — resolves `settings.default_chunk_size` references
  - `seed_strategies_from_yaml(db_session, yaml_path, settings)` — overwrites system strategies (`is_system=True`) in DB from YAML; skips user strategies (`is_system=False`)
- [x] 2.3 Replace hardcoded seeding block in `src/api/main.py` (lines 199-348) with call to `seed_strategies_from_yaml()` — keep old logic as fallback when YAML file missing
- [x] 2.4 Add graceful fallback: if YAML is missing or invalid, log warning and use existing hardcoded logic
- [x] 2.5 Remove factory methods `recursive_strategy()` and `semantic_strategy()` from `src/domain/entities.py` if no longer used elsewhere

## 3. API — GET /strategies/types endpoint

- [x] 3.1 Define `StrategyTypesResponse` Pydantic model with nested `StrategyTypeInfo` schema (params with type, default, description, enum, nullable)
- [x] 3.2 Create `STRATEGY_TYPE_SCHEMAS` static dict in `src/api/schemas/document.py` or a new `src/api/schemas/strategy_types.py` — contains the full schema definitions for recursive, semantic, and api-docs
- [x] 3.3 Add `GET /strategies/types` route in `src/api/routes/documents.py` — returns `STRATEGY_TYPE_SCHEMAS`, no auth required
- [x] 3.4 Verify the endpoint is documented in OpenAPI schema (FastAPI auto-docs)

## 4. Model — parent_interface on APIEnum, APIErrorCode, and new APIRecord

- [x] 4.1 Add `parent_interface: str | None = None` field to `APIEnum` in `src/domain/rag/api_docs/model/models.py`
- [x] 4.2 Add `parent_interface: str | None = None` field to `APIErrorCode` in `src/domain/rag/api_docs/model/models.py`
- [x] 4.3 Add new `APIRecordField` model to `src/domain/rag/api_docs/model/models.py`:
  ```python
  class APIRecordField(BaseModel):
      name: str
      type_annotation: str = ""
      description: str = ""
  ```
- [x] 4.4 Add new `APIRecord` model to `src/domain/rag/api_docs/model/models.py`:
  ```python
  class APIRecord(BaseModel):
      name: str
      fields: list[APIRecordField] = []
      description: str = ""
      parent_interface: str | None = None
  ```

## 5. Converter — heading_policy and type_patterns

- [x] 5.1 Add `get_config_value(strategy, key, default)` helper to safely read from `strategy.config` dict (handles null config)
- [x] 5.2 Modify `_extract_interface_name()` in `src/domain/rag/api_docs/extraction/converter.py` to accept the strategy's `type_patterns` config and detect entity type:
  - After extracting heading name, match against `type_patterns` patterns
  - Fall back to prefix-based detection if no patterns defined
  - Return `(name, entity_type)` tuple instead of just name
- [x] 5.3 Modify `_get_or_create_interface()` to accept a `heading_policy` config:
  - Check `ignore_levels` — skip heading entirely if level is in ignore list
  - Check `section_levels` — create section group (no APIInterface) if level is in section list
  - Check `interface_levels` — compute nesting depth from index in list
  - When depth > 0, find nearest shallower-depth interface and set `base_interface`
  - Only interfaces nest; enums/records remain flat (no `base_interface`)
- [x] 5.4 Update `process_document()` (main converter entry point) to pass strategy config through to `_get_or_create_interface()` and `_extract_interface_name()`
- [x] 5.5 Update `_process_method_table()` to use `method_table.return_type_col` and `method_table.name_col` from config (with fallback to 0 and 1)
- [x] 5.6 Populate `parent_interface` on enums and error codes during conversion:
  - In `convert()` method, for enum tables: extract interface name from `ctx.heading_text` via `_extract_interface_name()`, set `enum.parent_interface = iface_name`
  - Same for error-code tables: set `ec.parent_interface = iface_name` on each error code
  - When no interface heading detected, `parent_interface` remains `None`
- [x] 5.7 Add `self.records: list[APIRecord] = []` to `DocumentConverter.__init__()` — new instance attribute for collected records
- [x] 5.8 Add `elif table_type == "record":` branch in `convert()` method:
  - Call `self._convert_record_table(table)` to produce an `APIRecord`
  - If record is not None, set `record.parent_interface = _extract_interface_name(ctx.heading_text)` from heading context
  - Append to `self.records`
- [x] 5.9 Implement `_convert_record_table(self, table: RawTable) -> APIRecord | None` method:
  - Determine record name: prefer `table.caption`, fall back to heading context, then `"UnknownRecord"`
  - Detect columns: try `_find_column` with `_NAME_KW` and `_TYPE_KW` keywords; fall back to positional (col 0 = name, col 1 = type, col 2 = description)
  - Parse each data row into an `APIRecordField`
  - Return `APIRecord` or `None` if no valid rows
- [x] 5.10 Update `convert()` return dict to include `"records"` key with `self.records`

## 6. Graph Builder — nested chunk nodes + entity metadata

- [x] 6.1 Modify `ChunkGraphBuilder` in `src/domain/rag/api_docs/chunking/builder.py` to read `base_interface` from `APIInterface`:
  - When building chunk nodes, check `base_interface` on each interface
  - If set, nest the interface's chunks under the parent interface's chunks
  - Interfaces without `base_interface` remain at root level
- [x] 6.2 Pass `max_depth` and `include_entities` config through to graph builder — skip entities not in whitelist, limit tree depth
- [x] 6.3 Add `interface_name` to enum node metadata in `_add_enum()` — read from `enum_def.parent_interface` field (should match pattern used by method nodes)
- [x] 6.4 Add `interface_name` to error-code node metadata in `_add_error_code()` — read from `ec.parent_interface` field
- [x] 6.5 Verify that flat entities (enums/records/error_codes) remain at depth 0 regardless of heading position
- [x] 6.6 Add `_add_record(self, graph, record: APIRecord, source_doc)` method to `ChunkGraphBuilder`:
  - Create `record` node at depth 0 (or under parent interface if `record.parent_interface` is set)
  - Set metadata: `type_name` = record name, `interface_name` = `record.parent_interface`, `description` = record description
  - Create `record_field` child nodes for each `APIRecordField`: `name`, `type_annotation`, `description`, `interface_name` = parent `parent_interface`
- [x] 6.7 Update `build()` method signature to accept `records: list[APIRecord] | None = None` and iterate over records with `_add_record()`

## 7. Formatter — formatting parameters

- [x] 7.1 Modify `ChunkTextFormatter` in `src/domain/rag/api_docs/chunking/formatter.py` (or equivalent) to accept formatting params:
  - `format_style`: `"detailed"` = full descriptions + signatures; `"compact"` = names only
  - `include_signatures`: toggle method/field signatures
  - `include_descriptions`: toggle text descriptions
- [x] 7.2 Pass formatting params from strategy config through the processing pipeline

## 8. Configurable min_chunk_length

- [x] 8.1 Modify `src/domain/services/chunking.py` line 44 — replace hardcoded `20` with `self.strategy.config.get("min_chunk_length", 20)` when `config` is not None
- [x] 8.2 Verify `min_chunk_length` is exposed in the GET /strategies/types schema for recursive and semantic types

## 9. Tests

- [x] 9.1 Add unit test for YAML seeding: create temp YAML file, call seeder, verify strategies are created/upserted in DB
- [x] 9.2 Add unit test for YAML fallback: verify hardcoded seeding still works when YAML file is missing
- [x] 9.3 Add unit test for converter with `type_patterns`: headings matching patterns create correct entity types; non-matching headings become sections
- [x] 9.4 Add unit test for converter with `heading_policy`: interface_levels, section_levels, ignore_levels produce correct nesting; enums/records stay flat
- [x] 9.5 Add unit test for converter with `interface_levels` gaps: heading levels not contiguous produce correct depth assignment
- [x] 9.6 Add unit test for converter populating `parent_interface` on enums: enum under IFooBar heading gets `parent_interface="IFooBar"`; enum before any heading gets `None`
- [x] 9.7 Add unit test for converter populating `parent_interface` on error codes: same pattern as enum test
- [x] 9.8 Add unit test for converter processing record tables:
  - Record table with name/type/desc columns produces correct `APIRecord` with fields
  - Record table under IFooBar heading gets `parent_interface="IFooBar"`
  - Record with only 2 columns (name + type) produces fields with empty descriptions
  - Record table with no heading context produces `parent_interface=None`
- [x] 9.9 Add unit test for graph builder nesting: interfaces with `base_interface` create parent-child chunk structure
- [x] 9.10 Add unit test for graph builder metadata: enum nodes contain `interface_name` in metadata populated from `parent_interface`
- [x] 9.11 Add unit test for graph builder metadata: record nodes contain `interface_name` in metadata populated from `record.parent_interface`
- [x] 9.12 Add unit test for configurable `min_chunk_length`: recursive service rejects chunks below threshold from config
- [x] 9.13 Add unit test for GET /strategies/types: returns correct schema shapes for all three engine types
- [x] 9.14 Add unit test for formatter params: detailed vs compact output, signature/description toggling
- [x] 9.15 Run test suite: `uv run pytest tests/ -v -x` — fix any failures

## 10. Documentation

- [x] 10.1 Write `docs/chunking-strategies.md` with:
  - YAML file format specification
  - All config schema keys per engine type (with defaults and descriptions)
  - Complete YAML examples for recursive, semantic, and api-docs strategies
  - Migration guide for custom strategies
  - `heading_policy` and `type_patterns` deep-dive section with examples
  - Method table configuration explanation
  - Entity ownership: how `parent_interface` flows from headings through models to chunk metadata and RAG context
