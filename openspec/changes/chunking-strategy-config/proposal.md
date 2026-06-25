## Why

Chunking strategy parameters are currently hardcoded or spread across typed DB columns with sentinel values (e.g., `chunk_size=0` for api-docs). The api-docs strategy has no way to configure entity name extraction patterns, heading nesting behavior, formatting options, or chunk depth — all of which are currently hardcoded in the converter and graph builder. Adding a YAML-based config file as the source of truth for system strategies solves both: it centralizes strategy definitions in a human-readable format and introduces per-type config schemas that expose tunable parameters without schema migrations.

## What Changes

- New `config/strategies.yaml` file becomes the source of truth for all system chunking strategies (recursive, semantic, api-docs)
- `ChunkingStrategy` DB model gains a `config` JSON column for type-specific parameters (additive, backward-compatible)
- Startup seeding logic reads from `config/strategies.yaml` instead of hardcoded factory methods
- New `GET /strategies/types` endpoint exposes per-type config schemas for API discoverability
- api-docs strategy gains a config schema with:
  - `type_patterns` — regex patterns to extract entity names from headings (per supported type: interface, enum, record)
  - `heading_policy` — maps DOCX heading levels to interface nesting (interface_levels, section_levels, ignore_levels)
  - `method_table` — column layout for method tables (return_type_col, name_col)
  - Formatting params: `max_depth`, `include_entities`, `format_style`, `include_signatures`, `include_descriptions`, `min_chunk_length`
- `DocumentConverter` uses `type_patterns` and `heading_policy` to build nested interfaces (sets `APIInterface.base_interface`)
- `ChunkGraphBuilder` creates nested chunk nodes from interfaces with `base_interface` set
- `min_chunk_length` becomes configurable (currently hardcoded to 20 in `chunking.py`)
- `docs/chunking-strategies.md` companion guide documenting the YAML format and all config schemas

## Capabilities

### New Capabilities
- `strategy-yaml-config`: YAML config file at `config/strategies.yaml` as the source of truth for system strategy definitions; startup seeding; additive `config` JSON column migration; `GET /strategies/types` endpoint exposing per-type config schemas; companion guide at `docs/chunking-strategies.md`
- `api-docs-chunking-config`: Per-type config schema for the api-docs engine, including `type_patterns` (entity name extraction from headings), `heading_policy` (interface nesting from DOCX heading levels), `method_table` layout, and formatting parameters (`max_depth`, `include_entities`, `format_style`, `include_signatures`, `include_descriptions`, `min_chunk_length`); changes to `DocumentConverter` and `ChunkGraphBuilder` to consume these params

### Modified Capabilities
*(None — existing specs remain accurate; the changes are additive)*

## Impact

- **New file**: `config/strategies.yaml`
- **New file**: `docs/chunking-strategies.md`
- **Modified**: `src/domain/entities.py` — factory methods may read from YAML or be replaced by YAML seeding
- **Modified**: `src/infrastructure/database/models.py` — add `config` JSON column to `ChunkingStrategy`
- **Modified**: `src/api/schemas/document.py` — add `config` field to response/update schemas
- **Modified**: `src/domain/rag/api_docs/extraction/converter.py` — use `type_patterns` for name extraction and `heading_policy` for interface nesting (set `base_interface`)
- **Modified**: `src/domain/rag/api_docs/chunking/builder.py` — create nested chunk nodes from interfaces with `base_interface`
- **Modified**: `src/domain/services/chunking.py` — use configurable `min_chunk_length`
- **Modified**: Strategy seeding in lifespan (likely `src/core/` or `src/api/main.py`)
- **New route**: `GET /strategies/types` in strategy routes
- **No breaking changes** — DB migration is additive, existing strategies are unchanged
