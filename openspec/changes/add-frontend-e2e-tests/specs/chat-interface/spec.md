# Chat Interface — Delta Spec

## MODIFIED Requirements

### Requirement: RAG query answers are always rendered in the chat UI

The Chat page SHALL always display completed RAG query answers in the chat message area, regardless of whether the answer arrived during polling or at task completion. The answer SHALL persist across Streamlit reruns by being stored in `st.session_state.messages`.

The answer rendering SHALL handle these cases:
- Answers returned during "processing" status (progressive rendering during polling)
- Answers returned for the first time in a poll that also returns "completed" status
- Answers returned after the user's question message (maintain correct message ordering)
- Empty answers (skipped gracefully with a warning log)

#### Scenario: Answers rendered during polling survive rerun
- **WHEN** a polling cycle returns partial results with a completed backend answer
- **AND** the status is "processing"
- **THEN** the answer is rendered inline AND appended to `st.session_state.messages`
- **AND** on the next Streamlit rerun, the answer is still visible (rendered from session state)

#### Scenario: Answers returned with "completed" status are displayed
- **WHEN** a polling cycle returns results where status = "completed"
- **THEN** all results with a non-empty answer are rendered in the chat area
- **AND** the `poll_query_task()` cleanup does not remove the answer from `st.session_state.messages`
- **AND** the final rerun shows the answers in the message history

#### Scenario: Backend error does not prevent other answers from rendering
- **WHEN** one backend returns an error while another returns a successful answer
- **THEN** the failed backend shows an error message
- **AND** the successful backend's answer is rendered normally

#### Scenario: Answer is never appended before completion cleanup
- **WHEN** a poll returns status = "completed" with result entries that have not been rendered in a prior poll
- **THEN** each result with a non-empty answer IS appended to `st.session_state.messages` before the `task_started` flag is cleared
- **AND** the final rerun renders all answers from session state
