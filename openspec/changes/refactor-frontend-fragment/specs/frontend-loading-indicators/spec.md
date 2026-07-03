# Frontend Loading Indicators

## MODIFIED Requirements

### Requirement: Per-backend loading indicators during fragment-based polling dispatch

**MODIFIED** — The loading indicator pattern changes from ThreadPoolExecutor concurrent dispatch to `@st.fragment(run_every=1.0)`-based polling. Per-backend progress is now driven by the backend's async task progress field instead of `as_completed()` futures. The fragment provides a stable scope — no placeholder management, no sentinel flags.

When the frontend Chat page executes a multi-backend query via the async task polling pattern, it SHALL use `@st.fragment(run_every=1.0)` to poll task status and render progress. The fragment SHALL display a progress counter with per-backend status messages while the task is running, and SHALL render completed results inline as they arrive. The sidebar and message rendering loop SHALL remain stable across fragment reruns.

#### Scenario: Progress counter shown during fragment polling
- **WHEN** a query task is active and the fragment polls `GET /api/v1/query/status/{task_id}`
- **THEN** the fragment SHALL display a markdown header with the count of completed backends
- **THEN** the fragment SHALL display `st.info()` messages for any backends with active progress updates
- **THEN** the sidebar and previously rendered messages SHALL NOT re-execute or flicker

#### Scenario: Backend result appears inline on completion
- **WHEN** a backend completes and its answer appears in the poll response
- **THEN** the fragment SHALL render the answer inline using `st.chat_message("assistant")` with avatar and label
- **THEN** the result SHALL be persisted to `st.session_state.messages`
- **THEN** the remaining incomplete backends SHALL continue showing their progress indicators

#### Scenario: Error handled inline without breaking fragment
- **WHEN** a backend returns an error in the poll response
- **THEN** the fragment SHALL display an `st.error()` message for that backend
- **THEN** the error SHALL be recorded in session state
- **THEN** the fragment SHALL continue polling for remaining backends

#### Scenario: All results stored on completion
- **WHEN** the poll response shows `status: "completed"`
- **THEN** all backend results SHALL be in `st.session_state.messages`
- **THEN** `task_started` SHALL be set to `False`
- **THEN** the fragment SHALL stop re-executing on the next scheduled run
- **THEN** no `st.rerun()` SHALL be called — the next full page rerun (e.g., user interaction) SHALL render all messages from session state
