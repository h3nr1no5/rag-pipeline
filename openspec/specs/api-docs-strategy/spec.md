# API Docs Strategy

## Purpose

Define the chunking strategy for "API Documentation" documents and handle routing through the dedicated API doc extraction pipeline instead of the standard parse-chunk-embed loop.

## Requirements

### Requirement: System SHALL seed "API Documentation" strategy on startup

The application lifespan SHALL create an `api-docs` chunking strategy with `engine_type="api-docs"` if one does not already exist. This replaces the old removed `is_api_doc` flag and uses the strategy itself as the routing signal.

#### Scenario: Seed api-docs strategy on first startup
- **WHEN** the application starts and no `ChunkingStrategy` with `id="api-docs"` exists
- **THEN** the system SHALL create a new strategy with:
  - `id="api-docs"`
  - `name="API Documentation"`
  - `description="Structure-aware chunking for API documentation (DOCX/PDF)"`
  - `chunk_size=0`, `chunk_overlap=0`, `separators=[]` (N/A for this engine type)
  - `engine_type="api-docs"`
  - `use_hyperlinks=False`
  - `is_system=True`
  - `embedding_model` SHALL use the current settings value

#### Scenario: Existing api-docs strategy not duplicated
- **WHEN** the application starts and a `ChunkingStrategy` with `id="api-docs"` already exists
- **THEN** the system SHALL NOT create a duplicate
- **AND** the existing strategy SHALL be used as-is

### Requirement: Standard upload endpoint SHALL accept api-docs strategy

The `POST /documents` endpoint SHALL accept `strategy_id="api-docs"` and validate that the uploaded file is DOCX or PDF (not plain text, not PDF for semantic-only constraints).

#### Scenario: Upload DOCX with api-docs strategy succeeds
- **WHEN** a user uploads a `.docx` file with `strategy_id="api-docs"`
- **THEN** the upload SHALL succeed
- **THEN** a `Document` record SHALL be created with `chunking_strategy_id="api-docs"`
- **THEN** a `ProcessingConfig` SHALL be created with `engine_type="api-docs"`, `chunk_size=0`, `chunk_overlap=0`, `separators=[]`
- **AND** `trigger_document_processing()` SHALL be called

#### Scenario: Upload PDF with api-docs strategy succeeds
- **WHEN** a user uploads a `.pdf` file with `strategy_id="api-docs"`
- **THEN** the upload SHALL succeed
- **AND** the PDF SHALL be processed via the PDF fallback extractor (flat sections, no table detection)

#### Scenario: Upload unsupported file type with api-docs rejected
- **WHEN** a user uploads a `.txt` or other unsupported file type with `strategy_id="api-docs"`
- **THEN** the upload SHALL fail with an HTTP 400 error
- **AND** the error message SHALL indicate "API Documentation strategy only supports DOCX and PDF files"

### Requirement: Processor SHALL route api-docs engine type to dedicated pipeline

The `process_document_async()` function SHALL detect `engine_type="api-docs"` and branch to the dedicated API doc extraction/chunking pipeline instead of the standard parse-chunk-embed loop.

#### Scenario: Processor branches on engine_type
- **WHEN** the processor loads a `ProcessingConfig` with `engine_type="api-docs"`
- **THEN** it SHALL skip standard parsing (`parser_registry.parse`), standard chunking (`create_chunking_service`), and standard embedding loops
- **THEN** it SHALL call `_process_api_doc(document_id, file_path, doc_type)` instead
- **AND** standard progress tracking (`update_document_progress`, `mark_document_failed`) SHALL still apply

#### Scenario: api-docs document marked completed after processing
- **WHEN** `_process_api_doc()` completes successfully
- **THEN** `document.status` SHALL be set to `"completed"`
- **THEN** `document.processing_message` SHALL be `"Indexed for API doc querying"`
- **AND** `document.chunk_count` SHALL reflect the ChunkGraph node count