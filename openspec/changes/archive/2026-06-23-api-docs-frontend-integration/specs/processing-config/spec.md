## MODIFIED Requirements

### Requirement: ProcessingConfig stores effective processing parameters

**Modification**: The `engine_type` field now supports `"api-docs"` in addition to `"recursive"` and `"semantic"`. The `strategy_id` field can now be `"api-docs"`.

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

When a document is uploaded, the system SHALL merge strategy defaults with any user-provided overrides and create a `ProcessingConfig` record storing the effective parameters. For `api-docs` strategy, chunking parameters are fixed to N/A values (0/0/[]).

#### Scenario: Upload with api-docs strategy
- **WHEN** a user uploads a document with `strategy_id="api-docs"`
- **THEN** the system SHALL create a `ProcessingConfig` with:
  - `strategy_id="api-docs"`, `engine_type="api-docs"`
  - `chunk_size=0`, `chunk_overlap=0`, `separators=[]`, `use_hyperlinks=False`
- **AND** the api-docs strategy SHALL NOT accept user overrides for chunking parameters

## ADDED Requirements

### Requirement: Processor SHALL skip standard chunking for api-docs engine type

When the processor encounters `engine_type="api-docs"`, it SHALL NOT run standard parsing, chunking, or embedding. Instead, it SHALL delegate to the dedicated API doc extraction pipeline.

#### Scenario: Processor skips standard pipeline for api-docs
- **WHEN** the processor loads a `ProcessingConfig` with `engine_type="api-docs"`
- **THEN** it SHALL skip `parser_registry.parse(file_path)`
- **THEN** it SHALL skip `create_chunking_service()` and `chunking_service.chunk_text()`
- **THEN** it SHALL skip the standard embedding loop
- **AND** it SHALL call `_process_api_doc(document_id, file_path, doc_type)` instead
