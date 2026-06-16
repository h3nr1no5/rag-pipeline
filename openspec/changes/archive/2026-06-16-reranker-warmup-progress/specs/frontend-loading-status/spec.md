## ADDED Requirements

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
