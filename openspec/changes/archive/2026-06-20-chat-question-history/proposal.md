## Why

The chat input field has no question history — users cannot recall or re-use previously asked questions. When exploring a topic, they often want to revisit a previous question, rephrase it slightly, or ask the same question in a new context. Without shell-style up/down arrow history, they must retype or copy-paste. This is a basic UX gap familiar from terminals, search bars, and every messaging app.

## What Changes

- Add client-side question history tracking in `st.session_state` and `localStorage`
- Add JavaScript arrow-key handler (ArrowUp/ArrowDown) on the chat input for cycling through history, matching terminal/shell behavior
- Add a user-ID-scoped localStorage key so history doesn't leak between users on the same browser
- No backend changes — history is stored locally, no new API endpoints, no new database tables
- No changes to other pages or components

## Capabilities

### New Capabilities
- `chat-question-history`: Client-side question history for the chat input, persisted in localStorage and navigable via up/down arrow keys

### Modified Capabilities

(none — this is a purely additive frontend feature with no existing spec to modify)

## Impact

- **Modified file only**: `client/pages/3_💬_Chat.py` (~70 lines added)
- **Security**: Adds a second `unsafe_allow_html=True` injection site for the history JS + data; user-entered question text flows through `json.dumps()` into innerHTML, requiring explicit security review
- **Dependencies**: None (no new packages)
- **Backward compatibility**: Fully additive — existing behavior unchanged
