# Frontend Loading Indicators

## Purpose

Provide per-backend loading indicators during sequential RAG query execution, so users see visible progress while each backend runs in sequence.

## MODIFIED Requirements

### Requirement: Per-backend spinners during sequential query dispatch

**MODIFIED** — The loading indicator pattern changes from ThreadPoolExecutor + `as_completed()` placeholders to sequential `st.spinner()` wrapping each sync backend call. The behavior of showing per-backend progress and replacing indicators with results is preserved; the mechanism changes to sequential rather than concurrent.

When the frontend Chat page executes multiple RAG backends sequentially, it SHALL show a `st.spinner()` for each backend as it runs. Each spinner SHALL display the backend name (e.g., "Querying cosine...") and auto-resolve when the backend's sync endpoint returns. The result SHALL render inline below any previously completed backends.

#### Scenario: Sequential spinner appears for current backend
- **WHEN** the sequential loop begins executing a backend
- **THEN** a `st.spinner("Querying <backend>...")` SHALL be active for the duration of that backend's HTTP call
- **THEN** no placeholder management (`st.empty()` / `.empty()`) is needed — `st.spinner()` clears automatically

#### Scenario: Spinner replaced by result on completion
- **WHEN** a backend's sync endpoint returns a successful response (`{"answer": "..."}`)
- **THEN** the spinner SHALL disappear (auto-cleared by `st.spinner()` context manager)
- **THEN** the answer SHALL render at that position using `st.chat_message("assistant")` with avatar, label, and sources expander

#### Scenario: Error handling does not break the loop
- **WHEN** a backend's sync endpoint returns an error or raises an exception
- **THEN** the spinner SHALL disappear
- **THEN** an `st.error()` SHALL render showing the error details at that position
- **THEN** the loop SHALL continue to the next backend

#### Scenario: All results stored after loop completes
- **WHEN** the sequential loop finishes (all backends have succeeded, errored, or timed out)
- **THEN** all results SHALL be appended to `st.session_state.messages` in the original selection order
- **THEN** no `st.rerun()` is needed — answers are already rendered inline
