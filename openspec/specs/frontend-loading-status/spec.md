# Frontend Loading Status

## Purpose

Provide real-time feedback to users during model warmup by polling the backend health endpoint and displaying per-model progress bars, ensuring the application remains responsive and transparent about its initialization state.

## Requirements

### Requirement: Chat page SHALL poll model status on load

The Streamlit chat page SHALL poll `GET /health/models` every 200ms while any model is in `loading` status. Polling SHALL stop once all models are `ready` or `error`.

#### Scenario: Polling starts on page load
- **WHEN** the chat page loads
- **THEN** the page SHALL begin polling `/health/models` at 200ms intervals
- **THEN** each poll response SHALL be checked for model status values

#### Scenario: Polling stops when all models ready
- **WHEN** all models report `status: "ready"`
- **THEN** polling SHALL stop
- **THEN** no further `/health/models` requests SHALL be made until the next page load

#### Scenario: Polling stops on error
- **WHEN** a model reports `status: "error"`
- **THEN** polling SHALL stop immediately
- **THEN** an error indicator SHALL be shown for the failed model

### Requirement: Frontend SHALL display per-model progress bars

The chat page SHALL show a status bar section above the chat input area when any model is loading. Each model SHALL be displayed with its name and a progress bar.

#### Scenario: Progress bars shown during loading
- **WHEN** at least one model has `status: "loading"`
- **THEN** the page SHALL display a status section above the chat input
- **THEN** each loading model SHALL show its name and a progress bar reflecting the `progress` value

#### Scenario: No status section when all models ready
- **WHEN** all models are `status: "ready"`
- **THEN** the status section SHALL be hidden
- **THEN** the chat input SHALL be fully interactive

#### Scenario: Status section shows error state
- **WHEN** a model has `status: "error"`
- **THEN** the status section SHALL show an error indicator for that model
- **THEN** an error message MAY be displayed with guidance (e.g., "reload the page or contact support")

#### Scenario: Layout does not shift on polling
- **WHEN** the status section appears or disappears during polling
- **THEN** the status section SHALL use `st.empty()` placeholders to avoid page layout shifts

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
