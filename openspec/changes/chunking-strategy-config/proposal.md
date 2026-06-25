## Why

Chunking strategy parameters are currently hardcoded or spread across typed DB columns with sentinel values (e.g., `chunk_size=0` for api-docs). The api-docs strategy has no way to configure entity name extraction patterns, heading nesting behavior, formatting options, or chunk depth — all of which are currently hardcoded in the converter and graph builder. Adding a YAML-based config file that **overwrites system strategies on every startup** solves both: it centralizes strategy definitions in a human-readable file checked into version control and introduces per-type config schemas that expose tunable parameters without schema migrations.

## What Changes

- New `config/strategies.yaml` file is the source of truth for system strategies — **overwrites DB on every startup** (user strategies untouched)
- Three strategies defined: `Recursive` (recursive), `Semantic` (semantic), `API Documentation` (api-docs) — all with concrete codebase-derived params
- `ChunkingStrategy` DB model gains a `config` JSON column for type-specific parameters (additive, backward-compatible, nullable)
- Startup seeding logic reads from `config/strategies.yaml` instead of hardcoded factory methods; falls back to hardcoded logic if YAML missing
- New `GET /strategies/types` endpoint exposes per-type config schemas for API discoverability
- api-docs strategy gains a config schema with:
  - `type_patterns` — regex patterns to extract entity names from headings (whitelist approach per type: interface, enum, record; prefix fallback: I*, E*, R*)
  - `heading_policy` — maps DOCX heading levels to interface nesting (`interface_levels` with depth-by-index, `section_levels`, `ignore_levels`)
  - `method_table` — column layout for method tables (`return_type_col: 0`, `name_col: 1`)
  - Formatting params: `max_depth: 3`, `format_style: "detailed" | "compact"`, `include_signatures`, `include_descriptions`, `min_chunk_length: 20`
- `DocumentConverter` uses `type_patterns` and `heading_policy` to build nested interfaces (sets `APIInterface.base_interface`)
- `DocumentConverter` gains `table_type == "record"` handling — creates `APIRecord` with `APIRecordField` children from record/struct tables (currently silently dropped)
- New `APIRecord` and `APIRecordField` models with `parent_interface` (same ownership pattern as enums/error_codes)
- `ChunkGraphBuilder` creates nested chunk nodes from interfaces with `base_interface` set; flat entities (enum/record/error_code) stay at depth 0
- `min_chunk_length` becomes configurable via `config.min_chunk_length` (currently hardcoded to 20 in `chunking.py`)
- `docs/chunking-strategies.md` companion guide documenting the YAML format and all config schemas

## Config Schemas

### Top-Level Columns (all engines)
| Param | Type | Description |
|-------|------|-------------|
| `chunk_size` | int | Max chunk size (0 = N/A for api-docs) |
| `chunk_overlap` | int | Overlap between chunks |
| `separators` | list[str] | Split separator priority |
| `use_hyperlinks` | bool | Whether to include hyperlinks |
| `config` | dict \| null | Per-engine config (see below) |

### api-docs Engine: `config` Schema
```yaml
config:
  min_chunk_length: 20
  type_patterns:
    interface: ["^I[A-Z]\\w+"]      # I-prefixed = interface
    enum: ["^E[A-Z]\\w+"]           # E-prefixed = enum
    record: ["^R[A-Z]\\w+"]         # R-prefixed = record
  heading_policy:
    interface_levels: [0, 1, 2, 3, 4]  # All levels create interfaces; depth = list index
    section_levels: [3]                  # Level 3 = section group (no interface)
    ignore_levels: []                    # Never skip levels
  method_table:
    return_type_col: 0             # 1st column
    name_col: 1                    # 2nd column
  max_depth: 3
  format_style: "detailed"         # "detailed" | "compact"
  include_signatures: true
  include_descriptions: true
```

## Capabilities

### New Capabilities
- `strategy-yaml-config`: `config/strategies.yaml` with three system strategies; overwrite-on-startup seeding; additive `config` JSON column migration; `GET /strategies/types` endpoint exposing per-type config schemas including docs/chunking-strategies.md companion guide
- `api-docs-chunking-config`: Per-type config for api-docs with type_patterns, heading_policy, method_table, and formatting params; changes to DocumentConverter, ChunkGraphBuilder, and ChunkTextFormatter to consume these from the config column; **includes full record/struct pipeline (model → converter → builder → formatter → RAG context) with entity-to-interface ownership**

### Modified Capabilities
*(None — existing specs remain accurate; the changes are additive)*

## Impact

- **New file**: `config/strategies.yaml` — three strategies with concrete params from current codebase
- **New file**: `docs/chunking-strategies.md` — companion guide
- **New models**: `APIRecord`, `APIRecordField` (src/domain/rag/api_docs/model/models.py)
- **Modified**: `src/infrastructure/database/models.py` — add nullable `config` JSON column to `ChunkingStrategy`
- **Modified**: `src/api/schemas/document.py` — add `config: dict | None` to response/update schemas
- **Modified**: Strategy seeding in `src/api/main.py` — replace hardcoded block (lines 199-348) with YAML reader; keep fallback
- **Modified**: `src/infrastructure/strategies/seeder.py` — new module for YAML load + DB overwrite
- **Modified**: `src/domain/rag/api_docs/extraction/converter.py` — use `type_patterns` for entity detection, `heading_policy` for interface nesting (set `base_interface`), and add `table_type == "record"` branch with `_convert_record_table()` and `parent_interface` population for enums/records/error_codes
- **Modified**: `src/domain/rag/api_docs/chunking/builder.py` — create nested chunk nodes from interfaces with `base_interface` set; add `_add_record()` method and `records` parameter to `build()`
- **Modified**: `src/domain/rag/api_docs/chunking/formatter.py` — consume `format_style`, `include_signatures`, `include_descriptions`
- **Modified**: `src/domain/services/chunking.py` — use configurable `min_chunk_length` from `config.min_chunk_length`
- **Modified**: `src/domain/entities.py` — remove factory methods if no longer used elsewhere
- **New route**: `GET /strategies/types` in strategy routes
- **New dependency**: PyYAML (added to pyproject.toml)
- **No breaking changes** — DB migration is additive, existing strategies are unchanged
