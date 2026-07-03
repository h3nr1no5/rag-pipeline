# Frontend Loading Indicators

## Purpose

Provide per-backend loading indicators during concurrent RAG query dispatch, so users see visible progress while backends execute in parallel.

## Requirements

### Requirement: Per-backend loading indicators during concurrent query dispatch

When the frontend Chat page dispatches multiple RAG backends concurrently via `ThreadPoolExecutor`, it SHALL show a loading indicator for each selected backend *before* the blocking `as_completed()` call. Each indicator SHALL be replaced by the backend's answer as soon as that backend's future completes, providing the user with visible progress during the wait.

#### Scenario: Spinners visible before blocking wait

- **WHEN** a user submits a question with 3 backends selected (cosine, LangChain, LlamaIndex)
- **THEN** the page SHALL render 3 `st.chat_message("assistant")` containers with per-backend loading indicators before entering the `ThreadPoolExecutor` context
- **THEN** each indicator SHALL use `st.info("⏳ **Backend** — thinking...")` inside an `st.empty()` placeholder
- **THEN** the browser SHALL display these indicators before the 20-60s backend execution begins

#### Scenario: Indicator replaced by result on completion

- **WHEN** a backend future completes inside the `as_completed()` loop
- **THEN** its `st.empty()` placeholder SHALL be cleared via `.empty()`
- **THEN** a new container at the same position SHALL render the backend's answer using `render_message()` (with avatar, label, and sources expander)
- **THEN** the remaining unfinished backends SHALL continue showing their loading indicators

#### Scenario: Error handling preserves other indicators

- **WHEN** a backend future raises an exception or returns an error result (`{"error": true}`)
- **THEN** its placeholder SHALL be replaced with an `st.error()` message showing the error details
- **THEN** the other backends' loading indicators SHALL remain visible and unaffected

#### Scenario: All results stored after loop completes

- **WHEN** the `as_completed()` loop finishes (all backends have completed, errored, or timed out)
- **THEN** all results SHALL be appended to `st.session_state.messages` in the original selection order
- **THEN** `st.rerun()` SHALL be called to rebuild the page from canonical session state
