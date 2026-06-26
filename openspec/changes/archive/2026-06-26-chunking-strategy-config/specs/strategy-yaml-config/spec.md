## ADDED Requirements

### Requirement: YAML config file as source of truth for system strategies

The system SHALL read system strategy definitions from `config/strategies.yaml` at application startup and overwrite matching system strategies in the DB. The YAML file SHALL define default values for recursive, semantic, and api-docs strategies. The YAML file SHALL be tracked in version control. User-created strategies (`is_system=False`) SHALL NOT be affected.

**YAML structure:**
```yaml
strategies:
  recursive:
    name: "Recursive"
    description: "Recursive chunking for general documents"
    chunk_size: 1000          # default from settings.default_chunk_size
    chunk_overlap: 200        # default from settings.default_chunk_overlap
    separators: ["\n\n", "\n", ". "]
    engine_type: "recursive"
    use_hyperlinks: false
    is_system: true
    min_chunk_length: 20      # new configurable field
  semantic:
    name: "Semantic"
    description: "Semantic chunking for structured content"
    chunk_size: 300
    chunk_overlap: 30
    separators: ["\n## ", "\n### ", "\n", "## ", "### "]
    engine_type: "semantic"
    use_hyperlinks: false
    is_system: true
  api-docs:
    name: "API Documentation"
    description: "Structure-aware chunking for API documentation"
    engine_type: "api-docs"
    use_hyperlinks: false
    is_system: true
    config:
      type_patterns:
        interface: ["^I[A-Z]\\w+", "^[A-Z][a-zA-Z]+Interface$"]
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
      include_entities: null
      format_style: "detailed"
      include_signatures: true
      include_descriptions: true
      min_chunk_length: 20
```

#### Scenario: Seed system strategies from YAML at startup

- **WHEN** the application starts and `config/strategies.yaml` exists
- **THEN** the system SHALL read all `strategies` entries and overwrite matching system strategies in the `chunking_strategies` table
- **AND** existing system strategies (matched by `id`) SHALL have all their parameters replaced with YAML values
- **AND** missing system strategies SHALL be created
- **AND** user-created strategies (`is_system=False`) SHALL NOT be modified

#### Scenario: YAML file not found — graceful fallback

- **WHEN** the application starts and `config/strategies.yaml` does not exist
- **THEN** the system SHALL log a warning
- **AND** the system SHALL fall back to the existing hardcoded seeding logic (backward compatible)

#### Scenario: YAML validation failure

- **WHEN** `config/strategies.yaml` contains invalid YAML or missing required fields
- **THEN** the system SHALL log an error with details
- **AND** the system SHALL fall back to the existing hardcoded seeding logic

---

### Requirement: Additive `config` JSON column on ChunkingStrategy

The `chunking_strategies` table SHALL gain a nullable `config` JSON column. This column SHALL store type-specific configuration parameters as a JSON object. For recursive and semantic strategies, `config` SHOULD be `null`. For api-docs strategies, `config` SHALL contain `type_patterns`, `heading_policy`, `method_table`, and formatting parameters.

#### Scenario: Migration is additive and backward-compatible

- **WHEN** the database migration runs
- **THEN** existing rows SHALL have `config` set to `NULL`
- **AND** existing queries, inserts, and updates SHALL continue to work without modification

#### Scenario: Config is populated during YAML seeding

- **WHEN** a system strategy is seeded from `config/strategies.yaml` with a `config` key
- **THEN** the strategy's `config` column SHALL be overwritten with the JSON representation of the `config` object
- **AND** when a system strategy lacks a `config` key in YAML, its `config` column SHALL be set to `NULL`

---

### Requirement: `GET /strategies/types` endpoint

The system SHALL expose a `GET /strategies/types` endpoint that returns the per-type config schema available for each engine type. This enables UI clients to dynamically render config forms limited to params relevant to the selected strategy type.

**Response shape:**
```json
{
  "types": {
    "recursive": {
      "params": {
        "chunk_size": {"type": "integer", "default": 1000, "description": "Maximum chunk size in characters"},
        "chunk_overlap": {"type": "integer", "default": 200, "description": "Overlap between chunks"},
        "separators": {"type": "array", "items": "string", "default": ["\\n\\n", "\\n", ". "], "description": "Separator strings in priority order"},
        "min_chunk_length": {"type": "integer", "default": 20, "description": "Minimum chunk length to keep"}
      }
    },
    "semantic": {
      "params": {
        "chunk_size": {"type": "integer", "default": 300},
        "chunk_overlap": {"type": "integer", "default": 30},
        "separators": {"type": "array", "items": "string"},
        "use_hyperlinks": {"type": "boolean", "default": false},
        "min_chunk_length": {"type": "integer", "default": 20}
      }
    },
    "api-docs": {
      "config_schema": {
        "type_patterns": {"type": "object", "description": "Regex patterns per entity type"},
        "heading_policy": {"type": "object", "description": "Heading level to interface nesting rules"},
        "method_table": {"type": "object", "description": "Table column layout for methods"},
        "max_depth": {"type": "integer", "default": 3},
        "include_entities": {"type": "array", "items": "string", "nullable": true},
        "format_style": {"type": "string", "enum": ["detailed", "compact"], "default": "detailed"},
        "include_signatures": {"type": "boolean", "default": true},
        "include_descriptions": {"type": "boolean", "default": true},
        "min_chunk_length": {"type": "integer", "default": 20}
      }
    }
  }
}
```

#### Scenario: Returns config schema for all supported engine types

- **WHEN** a client calls `GET /strategies/types`
- **THEN** the response SHALL contain a `types` object with keys for each supported `engine_type`
- **AND** each type SHALL describe its configurable parameters with type, default, and description

#### Scenario: Schema is static and hardcoded

- **WHEN** a client calls `GET /strategies/types`
- **THEN** the response SHALL be a static description derived from code (not from the database)
- **AND** the endpoint SHALL NOT require authentication

---

### Requirement: `min_chunk_length` configurable on all strategies

The `min_chunk_length` parameter SHALL be configurable via the `config` JSON column. When omitted, the default value SHALL be 20. Recursive and semantic strategies SHALL also support `min_chunk_length` in their `config`.

#### Scenario: Recursive service reads min_chunk_length from config

- **WHEN** `RecursiveChunkingService.chunk_text()` filters chunks below minimum length
- **THEN** it SHALL read `min_chunk_length` from `self.strategy.config.get("min_chunk_length", 20)`
- **AND** when `config` is `null` or does not contain `min_chunk_length`, the value SHALL default to 20

---

### Requirement: Companion guide at `docs/chunking-strategies.md`

The project SHALL include a developer-facing guide documenting the YAML format, all supported config schema keys with defaults, example strategy definitions, and migration notes for custom strategies.

#### Scenario: Guide is reference-complete

- **WHEN** a developer reads `docs/chunking-strategies.md`
- **THEN** they SHALL find documentation for the YAML format, all config schema keys per engine type, and at least one complete example per engine type
