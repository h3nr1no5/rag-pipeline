## ADDED Requirements

### Requirement: Tests asserting saved_chunks == 0 after upload SHALL not race with background tasks

Integration tests that upload a document and immediately assert `saved_chunks == 0` SHALL prevent the background processing task (`trigger_document_processing`) from modifying the document state between the upload and the assertion.

#### Scenario: test_list_endpoint_returns_progress_fields is deterministic

- **WHEN** `test_list_endpoint_returns_progress_fields` is run
- **THEN** it SHALL consistently pass every time, regardless of background task timing

#### Scenario: test_status_endpoint_pending_doc_has_zero_saved_chunks is deterministic

- **WHEN** `test_status_endpoint_pending_doc_has_zero_saved_chunks` is run
- **THEN** it SHALL consistently pass every time, regardless of background task timing

#### Scenario: Existing patch pattern is used

- **WHEN** a test needs to suppress background processing
- **THEN** it SHALL use `@patch("src.domain.services.processor.trigger_document_processing", lambda doc_id: None)`
- **AND** it SHALL be consistent with the pattern already used for `test_reprocess_resets_saved_chunks`

### Requirement: Background task suppression SHALL not affect unrelated assertions

Patching `trigger_document_processing` SHALL only affect the test's ability to assert on document state. The upload endpoint SHALL still create the document record, return status 201, and include all required response fields.

#### Scenario: Upload response is unaffected by patch

- **WHEN** a test uploads a document with the patch active
- **THEN** the response SHALL include `id`, `title`, `status`, `saved_chunks`, and progress fields
- **AND** the response status SHALL be 201

#### Scenario: Status endpoint query is unaffected by patch

- **WHEN** a test calls GET `/documents/{id}/status` with the patch active
- **THEN** the response SHALL include all progress fields (`parsing_progress`, `chunking_progress`, `saving_progress`, `saved_chunks`, `stage_detail`)
- **AND** `saved_chunks` SHALL be 0 for a freshly uploaded document
