## ADDED Requirements

### Requirement: Frontend SHALL determine API doc query readiness from in-memory manager state

The chat page SHALL check the API Doc pipeline manager's in-memory index state (via `GET /query/api-docs/documents/{id}/status`) rather than the document's DB `status` field to determine whether an API doc is ready for querying. This accounts for the gap between DB persistence and in-memory index loading at startup.

#### Scenario: API doc shown as ready when manager has indexed it
- **WHEN** a user selects an API doc document
- **THEN** the frontend SHALL call `GET /api/v1/query/api-docs/documents/{id}/status`
- **WHEN** the response shows `indexed: true`
- **THEN** the document SHALL be shown as ready for querying
- **AND** the "🔶 API Docs" checkbox SHALL be enabled

#### Scenario: API doc shown as unavailable when manager has not indexed it
- **WHEN** the response shows `indexed: false`
- **THEN** the document SHALL show a loading indicator or "warming up" state
- **AND** the "🔶 API Docs" checkbox SHALL be disabled with a tooltip explaining the model is still warming up
