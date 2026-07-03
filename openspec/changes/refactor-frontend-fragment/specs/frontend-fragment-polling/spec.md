# Frontend Fragment Polling

## Purpose

Define how the Streamlit Chat page uses `@st.fragment(run_every=1.0)` to poll async query task status, render progress indicators, and display results — all without full-page reruns that could interrupt the message rendering loop.

## ADDED Requirements

### Requirement: Fragment SHALL poll task status with scoped reruns

The Chat page SHALL use `@st.fragment(run_every=1.0)` to wrap the async query polling logic. The fragment SHALL re-execute automatically at 1-second intervals while a query task is active (`task_started=True`). No explicit `st.rerun()` or `time.sleep()` calls SHALL be used inside the fragment.

#### Scenario: Fragment activates when task starts
- **WHEN** a user submits a question and `task_started` is set to `True`
- **THEN** the fragment SHALL begin polling `GET /api/v1/query/status/{task_id}` at 1-second intervals
- **THEN** the fragment SHALL re-execute without triggering a full page rerun
- **THEN** the sidebar and message rendering loop SHALL remain stable during polling

#### Scenario: Fragment stops when task completes
- **WHEN** the polled task returns `status: "completed"` or `status: "failed"`
- **THEN** the fragment SHALL set `task_started = False`
- **THEN** on the next scheduled fragment execution, the fragment SHALL detect no active task and return immediately
- **THEN** a full page rerun SHALL NOT be triggered — the fragment naturally stops

### Requirement: Fragment SHALL render progress indicators inline

The fragment SHALL display a progress counter showing how many backends have completed (e.g., "🔄 Query in progress... (2 backends complete)") and per-backend progress messages from the backend's `progress` field.

#### Scenario: Progress counter shown during query
- **WHEN** the poll response contains `results` with some backends complete
- **THEN** the fragment SHALL render a markdown header showing the completed count
- **THEN** any active progress messages from the `progress` field SHALL be shown as `st.info()` below the counter

#### Scenario: No progress shown when no query active
- **WHEN** `task_started` is `False`
- **THEN** the fragment SHALL render nothing (no progress, no errors, no results)

### Requirement: Fragment SHALL render completed results inline

When a poll response contains a backend result with an `answer` (and no `error`), the fragment SHALL render it inline using `st.chat_message("assistant")` with avatar, label, and sources expander. The result SHALL also be persisted to `st.session_state.messages` so it survives across page loads and full reruns.

#### Scenario: Backend result rendered inline on first sight
- **WHEN** a poll response contains a backend result with `answer` that has not been seen before
- **THEN** the fragment SHALL append the result to `st.session_state.messages` with role, content, sources, rag_type, and include_citations
- **THEN** the fragment SHALL render the answer inline using `st.chat_message("assistant")` with the appropriate colored avatar and label
- **THEN** if the result has sources, a `📚 Sources (N)` expander SHALL be shown

#### Scenario: Backend error rendered inline
- **WHEN** a poll response contains a backend result with `error`
- **THEN** the fragment SHALL render an `st.error()` with the backend label and error message
- **THEN** the error SHALL be persisted to session state

#### Scenario: API docs extras rendered after inline result
- **WHEN** the backend is `api_docs` and the result contains `confidence`, `reasoning_hint`, `relevant_functions`, or `relevant_types`
- **THEN** the confidence badge SHALL render below the answer
- **THEN** expandable sections for reasoning, relevant functions, and relevant types SHALL render if present

### Requirement: Fragment SHALL NOT use sentinel flags

The fragment SHALL NOT use `rendered_*` or `answer_stored_*` session state flags. The fragment's stable execution scope guarantees that each backend result is processed exactly once — no deduplication flags needed.

#### Scenario: No sentinel flags created or checked
- **WHEN** the fragment processes a poll response
- **THEN** it SHALL NOT create or check any `rendered_<task_id>_<backend>` or `answer_stored_<task_id>_<backend>` session state keys
- **THEN** it SHALL rely on the simple check "has this backend's result already been persisted to messages?" to avoid duplicates
