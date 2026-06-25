## Context

The RAG pipeline supports three chunking engines: **recursive** (general-purpose), **semantic** (structured content), and **api-docs** (API documentation DOCX/PDF). Each `ChunkingStrategy` row stores parameters in typed columns: `chunk_size`, `chunk_overlap`, `separators`, `engine_type`, `use_hyperlinks`, and `is_system`.

The api-docs engine has a fundamentally different architecture — it builds a structured chunk graph (interfaces → methods → fields) rather than splitting text — but the current schema forces sentinel values (`chunk_size=0`, `overlap=0`, `separators=[]`) to represent "not applicable." All api-docs-specific parameters (heading nesting rules, entity name regexes, formatting options) are hardcoded in pipeline code at import time — the converter (`src/domain/rag/api_docs/extraction/converter.py`), graph builder (`src/domain/rag/api_docs/chunking/builder.py`), and text formatter all have no runtime configuration path.

System strategies are seeded at startup in `src/api/main.py` (lines 199-348) with hardcoded literals for recursive, semantic, and api-docs strategies.

**Key pre-existing infrastructure:**
- `APIInterface` model already has an unused `base_interface: str | None` field (models.py line 31)
- `DocumentConverter` tracks a `heading_stack` (dict[int, str]) but discards nesting in `_get_or_create_interface()`
- `ChunkGraphBuilder` assigns all interfaces depth level 0
- `min_chunk_length = 20` is hardcoded in `RecursiveChunkingService.chunk_text()` (chunking.py line 44)

## Goals / Non-Goals

**Goals:**
- Replace hardcoded startup seeding with a `config/strategies.yaml` YAML source of truth
- Add an additive `config` JSON column to `ChunkingStrategy` for type-specific parameters
- Create a per-type config schema for api-docs: `type_patterns`, `heading_policy`, `method_table`, and formatting params
- Wire `config` parameters into converter, graph builder, and text formatter
- Make `min_chunk_length` configurable on all chunking strategies
- Expose config schemas via `GET /strategies/types` for UI discoverability
- Write a companion guide at `docs/chunking-strategies.md`
- Keep 100% backward compatibility — existing strategies and API contracts unchanged

**Non-Goals:**
- Migrate existing strategy rows to populate `config` — defaults are sufficient
- Add per-type validation/UI config forms (future work)
- Change the recursive or semantic chunking algorithms (only api-docs changes behavior)
- Introduce new chunking engines

## Decisions

### 1. YAML as config format (not JSON, TOML, or DB-only)

**Decision:** Use YAML at `config/strategies.yaml` as the source of truth for system strategies, overwriting the DB on every startup.

**Rationale:**
- YAML supports comments and anchors (critical for documenting regex patterns and strategy intent)
- Human-readable for developers who maintain strategy defaults
- A single file checked into version control replaces three factory methods and two lifespan blocks
- YAML overwrites DB on every startup — system strategies always reflect the YAML file; editing YAML + restart is the deployment workflow
- User-created strategies (`is_system=False`) are DB-only and never touched by YAML seeding
- JSON is less readable for complex nested regex configs; TOML lacks anchors; DB-only seeding hides defaults from developers

**Alternatives considered:**
- *DB-only with migration:* Harder to review in code review, no comments
- *JSON config:* Less readable with complex nested regex patterns
- *Python module:* Can't hot-reload or be edited by non-developers

### 2. `config` as a single JSON column (not separate typed columns)

**Decision:** A single `config` JSON column with a nullable `JSON?` type.

**Rationale:**
- Each engine type has a different config schema with different keys
- Adding typed columns for every possible config param creates schema churn
- JSON columns in SQLite/SQLAlchemy allow mixed types per engine
- The response schema uses `dict | None` with engine-specific key sets
- Backward compatible: existing rows return `config: null`

**Schema shape (all fields optional):**
```python
class ApiDocsConfig(TypedDict, total=False):
    type_patterns: dict[str, list[str]]  # {"interface": ["^I[A-Z]\\w+"], "enum": ["^E[A-Z]\\w+"], "record": ["^R[A-Z]\\w+"]}
    heading_policy: dict  # {"interface_levels": [0,1,2,3,4], "section_levels": [3], "ignore_levels": []}
    method_table: dict  # {"return_type_col": 0, "name_col": 1}
    max_depth: int  # default 3
    include_entities: list[str] | None  # None means all
    format_style: str  # "detailed" | "compact"
    include_signatures: bool  # default True
    include_descriptions: bool  # default True
    min_chunk_length: int  # default 20 (overrides global)
```

**Concrete YAML values** (extracted from current codebase — three strategies):
```yaml
strategies:
  - name: "Recursive"
    engine_type: "recursive"
    chunk_size: 500
    chunk_overlap: 50
    separators: ["\n\n", "\n", ". "]
  - name: "Semantic"
    engine_type: "semantic"
    chunk_size: 300
    chunk_overlap: 30
    separators: ["\n## ", "\n### ", "\n", "## ", "### "]
  - name: "API Documentation"
    engine_type: "api-docs"
    chunk_size: 0      # sentinel
    chunk_overlap: 0   # sentinel
    separators: []     # sentinel
    use_hyperlinks: true
    config:
      min_chunk_length: 20
      type_patterns:
        interface: ["^I[A-Z]\\w+"]
        enum: ["^E[A-Z]\\w+"]
        record: ["^R[A-Z]\\w+"]
      heading_policy:
        interface_levels: [0, 1, 2, 3, 4]
        section_levels: [3]
        ignore_levels: []
      method_table:
        return_type_col: 0
        name_col: 1
      max_depth: 3
      format_style: "detailed"
      include_signatures: true
      include_descriptions: true
```

### 3. Heading policy controls interface nesting in the converter

**Decision:** `heading_policy.interface_levels` maps DOCX heading styles to nesting levels. When a heading at level N is processed:
- If N is in `interface_levels`, a new interface is created (or reused if name matches)
- Its nesting depth equals the index of N within `interface_levels` (0 = root, 1 = child, etc.)
- `base_interface` is set to the parent interface's ID
- Only interfaces nest; enums, records, and error_codes remain flat (no `base_interface`)

**Rationale:**
- Problem: Currently all interfaces are at depth 0 regardless of heading nesting
- The heading_stack already exists in converter but is discarded
- Using index in `interface_levels` rather than raw heading number allows gaps (e.g., skip level 1)
- Flat entities (enum/record) should not nest even under deeply nested interfaces

### 4. Type patterns use a whitelist approach

**Decision:** `type_patterns` supplies one or more regex patterns per entity type. A heading name is matched against patterns of all types; the first matching type determines the entity type. If none match, the heading is treated as a section (grouping, not an interface).

**Entity type detection:**
1. Extract heading name via `_extract_interface_name()` (existing logic)
2. Match against `type_patterns` patterns in order: `interface`, `enum`, `record`, `error_code`
3. Fallback type check: name starts with `I` (uppercase) → interface, `E` → enum, `R` → record
4. If still no match → section (no APIInterface created)

**Rationale:**
- Regex patterns allow different naming conventions per project (e.g. Java's `InterfaceName` vs C# `IInterfaceName`)
- The prefix fallback maintains backward compatibility with existing docs
- Whitelist (matching types) prevents accidental entity creation from generic headings

### 5. `model_readiness_gate` as separate concern

**Decision:** The `model_readiness_gate` (warmup/early-exit) feature is not part of this change. It has existing specs and its own lifecycle.

### 6. Companion guide as developer-facing documentation

**Decision:** Write `docs/chunking-strategies.md` as a developer-facing reference, not part of auto-generated API docs.

**Content:**
- YAML format specification
- All supported config schema keys with defaults and descriptions
- Example strategy definitions for recursive, semantic, api-docs
- Migration guide for custom strategies

## Risks / Trade-offs

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| YAML file and DB diverge | None | YAML overwrites system strategies on every startup — they are always in sync by construction |
| `config` JSON column has no schema validation at DB level | Medium | Validate config at write time in Pydantic schemas and in `domain/entities.py` factory; YAML validation at seed time |
| `heading_policy` changes could produce different chunk structures for existing docs | Medium | Only affects re-processing (manual POST /documents/{id}/reprocess); existing chunks unchanged |
| Regex-based type patterns are brittle across different API doc styles | Medium | Provide sensible defaults (prefix-based fallback); document how to override in companion guide |
| Multiple config files to manage | Low | Single YAML file covers all system strategies; user strategies are DB-only |

## Migration Plan

**Deploy steps:**
1. Add `config` column to `ChunkingStrategy` model (additive ALTER TABLE)
2. Create `config/strategies.yaml` with current seed values (recursive, semantic, api-docs)
3. Replace hardcoded seeding in `src/api/main.py` lifespan with YAML reader + DB overwrite for system strategies
4. Add `GET /strategies/types` route endpoint
5. Implement `heading_policy` and `type_patterns` in converter
6. Implement nesting in `ChunkGraphBuilder`
7. Make `min_chunk_length` configurable
8. Write companion guide

**Rollback:** Revert the config column is additive and nullable — safe. The lifespan change reads YAML but falls back to existing behaviors if file is missing. Heading policy changes only affect re-processing. System strategies can be restored to previous YAML content by reverting the YAML file and restarting.

## Open Questions

1. Should `min_chunk_length` also be a top-level column on `ChunkingStrategy` (for non-api-docs engines), or only in `config` for api-docs? **Current decision:** Only in `config` for all engines; recursive/semantic default to `20` unless `config.min_chunk_length` is set. **(Resolved: config-only.)**
2. Should `config` be updatable via PATCH /strategies for custom strategies? **Current decision:** Yes, but system strategies remain immutable (403). Custom strategies can update `config` via PATCH.
3. Should `config` be visible in the strategy list (GET /strategies) or only in the detail endpoint? **Current decision:** Both — it's in the response schema.
