## 1. Foundation — YAML config file and DB migration

- [ ] 1.1 Create `config/` directory and `config/strategies.yaml` with seed definitions for recursive, semantic, and api-docs strategies — exact concrete values (params, type_patterns, heading_policy, method_table, formatting) are specified in `design.md` under "Concrete YAML values"
- [ ] 1.2 Add nullable `config` JSON column to `ChunkingStrategy` DB model (`src/infrastructure/database/models.py`) — use `JSON` type from SQLAlchemy, nullable=True, default=None
- [ ] 1.3 Add `config: dict | None` field to Pydantic response/update schemas in `src/api/schemas/document.py` (`ChunkingStrategyResponse`, `ChunkingStrategyUpdate`)

## 2. YAML seeding — replace hardcoded lifespan logic

- [ ] 2.1 Add PyYAML to project dependencies (`pyproject.toml`)
- [ ] 2.2 Create `src/infrastructure/strategies/seeder.py` with:
  - `load_strategies_from_yaml(path: str) -> dict` — reads YAML, validates structure, returns dict
  - `apply_config_overrides(settings, yaml_strategies)` — resolves `settings.default_chunk_size` references
  - `seed_strategies_from_yaml(db_session, yaml_path, settings)` — overwrites system strategies (`is_system=True`) in DB from YAML; skips user strategies (`is_system=False`)
- [ ] 2.3 Replace hardcoded seeding block in `src/api/main.py` (lines 199-348) with call to `seed_strategies_from_yaml()` — keep old logic as fallback when YAML file missing
- [ ] 2.4 Add graceful fallback: if YAML is missing or invalid, log warning and use existing hardcoded logic
- [ ] 2.5 Remove factory methods `recursive_strategy()` and `semantic_strategy()` from `src/domain/entities.py` if no longer used elsewhere

## 3. API — GET /strategies/types endpoint

- [ ] 3.1 Define `StrategyTypesResponse` Pydantic model with nested `StrategyTypeInfo` schema (params with type, default, description, enum, nullable)
- [ ] 3.2 Create `STRATEGY_TYPE_SCHEMAS` static dict in `src/api/schemas/document.py` or a new `src/api/schemas/strategy_types.py` — contains the full schema definitions for recursive, semantic, and api-docs
- [ ] 3.3 Add `GET /strategies/types` route in `src/api/routes/documents.py` — returns `STRATEGY_TYPE_SCHEMAS`, no auth required
- [ ] 3.4 Verify the endpoint is documented in OpenAPI schema (FastAPI auto-docs)

## 4. Converter — heading_policy and type_patterns

- [ ] 4.1 Add `get_config_value(strategy, key, default)` helper to safely read from `strategy.config` dict (handles null config)
- [ ] 4.2 Modify `_extract_interface_name()` in `src/domain/rag/api_docs/extraction/converter.py` to accept the strategy's `type_patterns` config and detect entity type:
  - After extracting heading name, match against `type_patterns` patterns
  - Fall back to prefix-based detection if no patterns defined
  - Return `(name, entity_type)` tuple instead of just name
- [ ] 4.3 Modify `_get_or_create_interface()` to accept a `heading_policy` config:
  - Check `ignore_levels` — skip heading entirely if level is in ignore list
  - Check `section_levels` — create section group (no APIInterface) if level is in section list
  - Check `interface_levels` — compute nesting depth from index in list
  - When depth > 0, find nearest shallower-depth interface and set `base_interface`
  - Only interfaces nest; enums/records remain flat (no `base_interface`)
- [ ] 4.4 Update `process_document()` (main converter entry point) to pass strategy config through to `_get_or_create_interface()` and `_extract_interface_name()`
- [ ] 4.5 Update `_process_method_table()` to use `method_table.return_type_col` and `method_table.name_col` from config (with fallback to 0 and 1)

## 5. Graph Builder — nested chunk nodes

- [ ] 5.1 Modify `ChunkGraphBuilder` in `src/domain/rag/api_docs/chunking/builder.py` to read `base_interface` from `APIInterface`:
  - When building chunk nodes, check `base_interface` on each interface
  - If set, nest the interface's chunks under the parent interface's chunks
  - Interfaces without `base_interface` remain at root level
- [ ] 5.2 Pass `max_depth` and `include_entities` config through to graph builder — skip entities not in whitelist, limit tree depth
- [ ] 5.3 Verify that flat entities (enums/records) remain at depth 0 regardless of heading position

## 6. Formatter — formatting parameters

- [ ] 6.1 Modify `ChunkTextFormatter` in `src/domain/rag/api_docs/chunking/formatter.py` (or equivalent) to accept formatting params:
  - `format_style`: `"detailed"` = full descriptions + signatures; `"compact"` = names only
  - `include_signatures`: toggle method/field signatures
  - `include_descriptions`: toggle text descriptions
- [ ] 6.2 Pass formatting params from strategy config through the processing pipeline

## 7. Configurable min_chunk_length

- [ ] 7.1 Modify `src/domain/services/chunking.py` line 44 — replace hardcoded `20` with `self.strategy.config.get("min_chunk_length", 20)` when `config` is not None
- [ ] 7.2 Verify `min_chunk_length` is exposed in the GET /strategies/types schema for recursive and semantic types

## 8. Tests

- [ ] 8.1 Add unit test for YAML seeding: create temp YAML file, call seeder, verify strategies are created/upserted in DB
- [ ] 8.2 Add unit test for YAML fallback: verify hardcoded seeding still works when YAML file is missing
- [ ] 8.3 Add unit test for converter with `type_patterns`: headings matching patterns create correct entity types; non-matching headings become sections
- [ ] 8.4 Add unit test for converter with `heading_policy`: interface_levels, section_levels, ignore_levels produce correct nesting; enums/records stay flat
- [ ] 8.5 Add unit test for converter with `interface_levels` gaps: heading levels not contiguous produce correct depth assignment
- [ ] 8.6 Add unit test for graph builder nesting: interfaces with `base_interface` create parent-child chunk structure
- [ ] 8.7 Add unit test for configurable `min_chunk_length`: recursive service rejects chunks below threshold from config
- [ ] 8.8 Add unit test for GET /strategies/types: returns correct schema shapes for all three engine types
- [ ] 8.9 Add unit test for formatter params: detailed vs compact output, signature/description toggling
- [ ] 8.10 Run test suite: `uv run pytest tests/ -v -x` — fix any failures

## 9. Documentation

- [ ] 9.1 Write `docs/chunking-strategies.md` with:
  - YAML file format specification
  - All config schema keys per engine type (with defaults and descriptions)
  - Complete YAML examples for recursive, semantic, and api-docs strategies
  - Migration guide for custom strategies
  - `heading_policy` and `type_patterns` deep-dive section with examples
  - Method table configuration explanation
