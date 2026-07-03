## ADDED Requirements

### Requirement: Stable fragment polling

The Streamlit `@fragment(run_every=1.0)` SHALL poll the `/query/status/{task_id}` endpoint and store results in `st.session_state`, but SHALL NOT render chat messages or expanders directly. The fragment's only visible output SHALL be status indicators and error messages.

- The fragment SHALL check `task_started` flag on each poll and return early if false
- The fragment SHALL poll with the stored `active_task_id` and JWT token
- When new results are detected (unrendered backend answers), the fragment SHALL call `st.rerun()` to trigger a full page rerun
- The main message loop SHALL render all stored messages via `render_message()` on the full page rerun
- The fragment SHALL NOT render `st.chat_message()` or `st.expander()` elements directly

#### Scenario: Fast backend completes before slow backend
- **WHEN** cosine backend completes with an answer
- **THEN** the fragment detects the new result on its next poll
- **THEN** the fragment stores the result in `st.session_state.messages`
- **THEN** the fragment calls `st.rerun()`
- **THEN** the main message loop renders the cosine answer
- **THEN** the fragment continues polling for remaining backends
- **THEN** the cosine answer remains visible (not replaced by subsequent fragment reruns)

#### Scenario: All backends complete
- **WHEN** all backends have completed
- **THEN** the fragment renders a completion signal
- **THEN** the fragment sets `task_started = False`
- **THEN** the fragment calls `st.rerun()`
- **THEN** the main loop renders all final messages
- **THEN** the fragment returns early on subsequent polls (task_started is false)

### Requirement: Fragment short-circuit guard (mandatory)

The fragment SHALL include a short-circuit guard that prevents calling `st.rerun()` when no new results have arrived since the last poll. This is REQUIRED to prevent infinite rerun loops.

- After polling, the fragment SHALL compare the current number of results against `st.session_state.rendered_backends`
- If no new results exist and the task is still running, the fragment SHALL return without calling `st.rerun()`
- The fragment SHALL only call `st.rerun()` when: (a) new results are detected, (b) the task completes, or (c) the timeout fires

#### Scenario: No new results during polling
- **WHEN** the fragment polls and finds no new results
- **THEN** the fragment returns early without calling `st.rerun()`
- **THEN** the fragment auto-reruns at the next 1-second interval
- **THEN** no infinite rerun loop occurs

#### Scenario: New result triggers rerun
- **WHEN** the fragment polls and finds a new result
- **THEN** the fragment stores the result in `st.session_state.messages`
- **THEN** the fragment calls `st.rerun()` once
- **THEN** the main loop renders the new result
- **THEN** the fragment re-executes after the rerun and returns early (no more new results)

### Requirement: Timeout guard with fallback rendering

The frontend SHALL have a 120-second timeout guard that prevents indefinite waiting. When the timeout fires, the system SHALL ensure all accumulated results are rendered before showing the error.

- The timeout guard SHALL check `time.time() - created_at > _FRONTEND_QUERY_TIMEOUT` and `status not in ("completed", "failed")`
- When timeout fires, the fragment SHALL render `st.error("⏰ Query timed out after {timeout} seconds")`
- When timeout fires, the fragment SHALL call `st.rerun()` BEFORE returning
- The main message loop SHALL render all accumulated `st.session_state.messages` on the rerun triggered by timeout
- The timeout error SHALL appear alongside (not in place of) any completed backend answers

#### Scenario: Timeout while some backends have completed
- **WHEN** 120 seconds have elapsed (or `_FRONTEND_QUERY_TIMEOUT` value)
- **WHEN** cosine and LlamaIndex have completed but LangChain is still running
- **THEN** the timeout guard fires
- **THEN** `st.session_state.task_started` is set to False
- **THEN** `st.error()` renders a timeout message
- **THEN** `st.rerun()` triggers a full page rerun
- **THEN** the main message loop renders the cosine and LlamaIndex answers
- **THEN** the user sees both answers plus the timeout message

#### Scenario: Timeout before any backend completes
- **WHEN** 120 seconds have elapsed (or `_FRONTEND_QUERY_TIMEOUT` value)
- **WHEN** no backends have completed yet
- **THEN** the timeout guard fires
- **THEN** `st.error()` renders a timeout message
- **THEN** `st.rerun()` triggers a full page rerun
- **THEN** no answers are shown (none completed)
- **THEN** the user sees only the timeout error

### Requirement: Configurable frontend timeout via environment variable

The frontend timeout value SHALL be configurable via the `FRONTEND_QUERY_TIMEOUT` environment variable. The default SHALL be 120 seconds. This enables E2E testing of timeout behavior without requiring a 2-minute wait.

- The system SHALL read `FRONTEND_QUERY_TIMEOUT` from `os.environ` at module load or first access
- If the env var is unset or invalid, the system SHALL default to `120`
- The timeout check SHALL use this value: `time.time() - created_at > _FRONTEND_QUERY_TIMEOUT`
- The error message SHALL display the actual timeout value used

#### Scenario: Default timeout in production
- **WHEN** `FRONTEND_QUERY_TIMEOUT` is not set
- **THEN** the timeout guard uses 120 seconds
- **THEN** the error message reads "Query timed out after 120 seconds"

#### Scenario: Short timeout in tests
- **WHEN** `FRONTEND_QUERY_TIMEOUT=5` is set
- **THEN** the timeout guard uses 5 seconds
- **THEN** an E2E test can trigger and verify timeout behavior in under 10 seconds

#### Scenario: Invalid value falls back to default
- **WHEN** `FRONTEND_QUERY_TIMEOUT=invalid` is set
- **THEN** the `int()` conversion raises `ValueError`
- **THEN** the system catches the error and defaults to 120 seconds

### Requirement: Message persistence across reruns

Rendered backend answers SHALL persist in the UI across fragment reruns and full page reruns until the user starts a new query or clears the chat.

- `st.session_state.messages` SHALL accumulate all backend answers
- The main message loop SHALL render all entries in `st.session_state.messages` on each full page rerun
- Fragment reruns SHALL NOT remove or interfere with messages rendered by the main loop
- A new query SHALL clear `st.session_state.messages` and `st.session_state.rendered_backends` and start fresh

#### Scenario: Fragment reruns during polling
- **WHEN** the fragment reruns every 1 second while polling
- **THEN** previously rendered answers in the main message loop remain visible
- **THEN** the fragment does not re-render or duplicate existing answers

#### Scenario: New query clears state
- **WHEN** user submits a new query
- **THEN** `st.session_state.messages` is cleared
- **THEN** `st.session_state.rendered_backends` is cleared
- **THEN** the previous answers are no longer displayed

### Requirement: Source expander shows dynamic count

The `render_message()` function in `client/components/chat_message.py` SHALL display the number of sources in the expander label, matching the previous behavior of the inline fragment rendering.

#### Scenario: Sources displayed with count
- **WHEN** a backend result has 3 sources
- **THEN** the expander label reads `"📚 Sources (3)"`
- **THEN** expanding the section shows all 3 source entries
