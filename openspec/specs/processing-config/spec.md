# Processing Config

## Purpose

Record the effective chunking parameters used to process a document at a specific point in time. The `ProcessingConfig` entity stores a full copy of all processing-relevant parameters — decoupled from the `ChunkingStrategy` entity so that strategy changes do not retroactively affect already-processed documents, and so that per-document parameter overrides can be supported.

## Requirements

### Requirement: ProcessingConfig stores effective processing parameters

The system SHALL have a `ProcessingConfig` entity that stores a complete snapshot of all chunking parameters used for a single document processing event. The entity SHALL be a full copy (not a diff) for direct consumption by the processor without merge logic.

#### Scenario: ProcessingConfig contains all strategy-relevant fields
- **WHEN** a `ProcessingConfig` record is created
- **THEN** it SHALL contain these fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `document_id` | UUID (FK → documents) | The document this config was used for |
| `strategy_id` | string | The strategy ID this config is based on (e.g., `"recursive"`, `"semantic"`, `"api-docs"`) |
| `chunk_size` | int | Effective chunk size in tokens (50-2000; 0 for api-docs) |
| `chunk_overlap` | int | Effective chunk overlap in tokens (0-500; 0 for api-docs) |
| `separators` | JSON | Effective list of separator strings (empty for api-docs) |
| `use_hyperlinks` | bool | Whether hyperlinks were processed |
| `engine_type` | string | `"recursive"`, `"semantic"`, or `"api-docs"` |
| `created_at` | datetime | When this config was created |

- **AND** every field SHALL contain the actual value used during processing (no merge or derivation needed at read time)

### Requirement: ProcessingConfig is created at document upload

When a document is uploaded, the system SHALL merge strategy defaults with any user-provided overrides and create a `ProcessingConfig` record storing the effective parameters. For api-docs strategy, chunking parameters are fixed to N/A values (0/0/[]).

#### Scenario: Upload with strategy only (no overrides)
- **WHEN** a user uploads a document with `strategy_id="recursive"` and no override parameters
- **THEN** the system SHALL create a `ProcessingConfig` with the strategy's default values for all fields
- **AND** SHALL assign the config's `id` to `document.current_processing_config_id`

#### Scenario: Upload with overrides
- **WHEN** a user uploads a document with `strategy_id="semantic"` and provides `chunk_size=600` as an override
- **THEN** the system SHALL create a `ProcessingConfig` with the strategy's values, except `chunk_size` which SHALL be `600`
- **AND** SHALL use the override value as-is — no clamping to strategy defaults

#### Scenario: Override all parameters
- **WHEN** a user uploads a document with `strategy_id="recursive"` and provides `{chunk_size, chunk_overlap, separators, use_hyperlinks}` as overrides
- **THEN** the system SHALL create a `ProcessingConfig` using the provided overrides for all fields
- **AND** only `strategy_id` and `engine_type` SHALL come from the strategy (engine_type is not overrideable)

#### Scenario: Upload with api-docs strategy
- **WHEN** a user uploads a document with `strategy_id="api-docs"`
- **THEN** the system SHALL create a `ProcessingConfig` with:
  - `strategy_id="api-docs"`, `engine_type="api-docs"`
  - `chunk_size=0`, `chunk_overlap=0`, `separators=[]`, `use_hyperlinks=False`
- **AND** the api-docs strategy SHALL NOT accept user overrides for chunking parameters

### Requirement: Processor reads from ProcessingConfig

The document processing pipeline SHALL read its chunking parameters from the document's linked `ProcessingConfig`, not directly from the `ChunkingStrategy`.

#### Scenario: Processor uses ProcessingConfig for chunking
- **WHEN** the processor begins processing a document
- **THEN** it SHALL load the `ProcessingConfig` record linked by `document.current_processing_config_id`
- **AND** SHALL use `ProcessingConfig.chunk_size`, `ProcessingConfig.chunk_overlap`, `ProcessingConfig.separators`, and `ProcessingConfig.use_hyperlinks` for all chunking decisions
- **AND** SHALL NOT load or reference the `ChunkingStrategy` entity for param values at processing time

#### Scenario: Processor passes params to semantic engine
- **WHEN** the engine type is `"semantic"`
- **THEN** the processor SHALL call the semantic chunking engine with `chunk_size` and `chunk_overlap` from the `ProcessingConfig`
- **AND** SHALL pass `chunk_size` as the max token limit (replacing the previous hardcoded `max_tokens=800`)

### Requirement: Reprocessing creates a new ProcessingConfig

When a document is reprocessed, the system SHALL create a new `ProcessingConfig` with the current effective parameters (not reuse the original), maintaining an audit trail of config changes.

#### Scenario: Reprocess with current strategy defaults
- **WHEN** a user requests reprocessing without providing override params
- **THEN** the system SHALL create a new `ProcessingConfig` using the current strategy's default values (which may have changed since the original processing)
- **AND** SHALL update `document.current_processing_config_id` to point to the new config
- **AND** the old `ProcessingConfig` record SHALL be retained (not deleted)

#### Scenario: Reprocess with new overrides
- **WHEN** a user requests reprocessing and provides new override parameters
- **THEN** the system SHALL create a new `ProcessingConfig` merging the current strategy defaults with the new overrides
- **AND** SHALL process the document with the new effective parameters
- **AND** the old `ProcessingConfig` SHALL be retained for audit purposes

### Requirement: API endpoints for ProcessingConfig

The system SHALL expose ProcessingConfig data through the API for transparency and debugging.

#### Scenario: ProcessingConfig included in document response
- **WHEN** a client fetches a document via `GET /documents/{id}`
- **THEN** the response SHALL include a `processing_config` nested object with the current config's fields
- **AND** SHALL include a `processing_configs` array listing all historical configs for that document

#### Scenario: List all configs for a document
- **WHEN** a client requests `GET /documents/{id}/processing-configs`
- **THEN** the response SHALL return an array of all `ProcessingConfig` records for that document, ordered by `created_at` descending

### Requirement: Processor SHALL skip standard chunking for api-docs engine type

When the processor encounters `engine_type="api-docs"`, it SHALL NOT run standard parsing, chunking, or embedding. Instead, it SHALL delegate to the dedicated API doc extraction pipeline.

#### Scenario: Processor skips standard pipeline for api-docs
- **WHEN** the processor loads a `ProcessingConfig` with `engine_type="api-docs"`
- **THEN** it SHALL skip `parser_registry.parse(file_path)`
- **THEN** it SHALL skip `create_chunking_service()` and `chunking_service.chunk_text()`
- **THEN** it SHALL skip the standard embedding loop
- **AND** it SHALL call `_process_api_doc(document_id, file_path, doc_type)` instead
