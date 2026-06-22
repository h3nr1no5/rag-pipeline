# Chat Question History

## Purpose

Define the requirements for persisting and navigating question history in the chat interface, providing users with quick access to previously asked questions and a shell-like navigation experience.

## Requirements

### Requirement: Question history is stored per user in browser localStorage

The system SHALL maintain a list of previously submitted questions per user, persisted in the browser's localStorage. Each user's history SHALL be keyed by a user-specific identifier (first 8 characters of the user's UUID) to isolate history between users on the same browser.

- The localStorage key format SHALL be `rag_question_history_{user_id_hash}` where `user_id_hash` is the first 8 characters of the authenticated user's UUID
- History SHALL be capped at 200 entries (oldest entries evicted when exceeded)
- Consecutive duplicate questions SHALL NOT create separate entries (same question as the most recent entry is ignored)
- Empty questions (blank/whitespace-only) SHALL NOT be recorded
- On logout, the current user's history key SHALL be removed from localStorage

#### Scenario: Question recorded after successful submission
- **WHEN** a user submits a non-empty question via chat input
- **THEN** the question SHALL be prepended to the history list in localStorage

#### Scenario: Consecutive duplicate suppressed
- **WHEN** a user submits the same question twice in a row
- **THEN** the second submission SHALL NOT create a duplicate history entry

#### Scenario: Empty question not recorded
- **WHEN** a user submits an empty or whitespace-only question
- **THEN** no history entry SHALL be created

#### Scenario: History capped at 200
- **WHEN** the history reaches 200 entries and a new question is submitted
- **THEN** the oldest entry SHALL be removed before adding the new one

#### Scenario: History keyed by user
- **WHEN** user A is logged in and submits questions
- **THEN** the localStorage key SHALL contain user A's ID hash
- **WHEN** user A logs out
- **THEN** the localStorage key for user A SHALL be removed

### Requirement: Chat input supports arrow-key navigation through question history

The chat input element SHALL support ArrowUp and ArrowDown key presses for cycling through question history, matching terminal/shell behavior.

- ArrowUp: Cycle backward through history (older questions). If at the most recent history entry, save the current draft text before replacing.
- ArrowDown: Cycle forward through history (newer questions). If at the most recent entry, restore the saved draft text.
- The input value SHALL be replaced with the selected history entry's text
- The cursor SHALL be placed at the end of the input text after navigation
- The browser's default ArrowUp/ArrowDown behavior (cursor to start/end of input) SHALL be prevented during history navigation
- The handler SHALL use a query selector with a retry fallback to find the chat input element even if Streamlit's DOM rendering is delayed

#### Scenario: ArrowUp shows previous question
- **WHEN** the user presses ArrowUp on the chat input
- **THEN** the input value SHALL be replaced with the most recent history entry

#### Scenario: ArrowDown returns to draft
- **WHEN** the user has navigated back through history and presses ArrowDown at the most recent entry
- **THEN** the input value SHALL be restored to the user's saved draft text

#### Scenario: ArrowUp at oldest entry stays at oldest
- **WHEN** the user presses ArrowUp while viewing the oldest history entry
- **THEN** the input value SHALL remain at the oldest entry

#### Scenario: ArrowDown with no history shows empty
- **WHEN** there is no question history and the user presses ArrowDown
- **THEN** the input value SHALL NOT change

### Requirement: New questions from Python session state are synced to localStorage

The JavaScript handler SHALL read the current session's question history from a hidden DOM element (populated by Python from `st.session_state`) and merge any new questions into the localStorage history.

- The Python code SHALL maintain `st.session_state.question_history` as the source of truth within the session
- After each successful question submission, Python SHALL prepend the question to `st.session_state.question_history` (capped at 200)
- The history SHALL be embedded in the page as a `<div>` with `id="q-history-data"` and `data-history` attribute containing the JSON-encoded list
- The JavaScript SHALL read this div on page load, merge unseen entries into localStorage, and update the localStorage copy

#### Scenario: Page load syncs session to localStorage
- **WHEN** the chat page loads and the hidden div contains history entries not yet in localStorage
- **THEN** those entries SHALL be merged into localStorage (prepended, maintaining order)
- **AND** the localStorage copy SHALL be updated atomically

#### Scenario: Empty history div handled gracefully
- **WHEN** the hidden div has an empty history array or is absent
- **THEN** the JavaScript SHALL fall back to whatever is already in localStorage
