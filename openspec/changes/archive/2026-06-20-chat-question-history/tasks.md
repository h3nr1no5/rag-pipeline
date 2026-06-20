## 1. Python: Session State History Tracking

- [x] 1.1 Initialize `st.session_state.question_history` as empty list if not present
- [x] 1.2 After successful question submission (in the `if prompt:` block), prepend the question to `st.session_state.question_history` — but only if it differs from the most recent entry (consecutive duplicate suppression) and is non-empty
- [x] 1.3 Cap `question_history` at 200 entries, evicting from the end
- [x] 1.4 Embed the history as a hidden `<div id="q-history-data" data-history='...'>` at the bottom of the page via `st.markdown` with `unsafe_allow_html=True`
- [x] 1.5 Add user-ID-scoped localStorage key derivation: compute `user_id_hash` from `st.session_state.user_id` (first 8 chars of UUID) and pass it to the JS

## 2. JavaScript: Arrow-Key Handler

- [x] 2.1 Read history from the hidden `#q-history-data` div on page load, merge unseen entries into localStorage under `rag_question_history_{user_id_hash}` key
- [x] 2.2 Implement the `keydown` listener on the chat input element (query selector with retry fallback):
  - ArrowUp: cycle backward (save draft on first press), prevent default browser behavior
  - ArrowDown: cycle forward, restore saved draft at newest position
  - Place cursor at end of input value after navigation
- [x] 2.3 Handle edge cases: empty history, out-of-bounds index, input element not yet rendered

## 3. JavaScript: Logout Cleanup

- [x] 3.1 The existing `logout()` function in `client/utils/api_client.py` — add a call to `localStorage.removeItem('rag_question_history_{user_id_hash}')` so history is cleared when the user logs out
- [x] 3.2 Verify the user ID hash is accessible at logout time (or compute it from the stored token/user info)

## 4. Security Review & Documentation

- [x] 4.1 Flag the new `unsafe_allow_html=True` usage for mandatory @security review — note that user-supplied question text flows through `json.dumps()` into `innerHTML`, and that this is the second such site in Chat.py (the first is the auto-focus script)
- [x] 4.2 Add a code comment at the JS injection site explaining the XSS mitigation (json.dumps escaping) and the rationale for using unsafe_allow_html

## 5. Verification

- [x] 5.1 Manual test: submit several questions → verify ArrowUp cycles through them in reverse order
- [x] 5.2 Manual test: verify ArrowDown returns to draft text after navigating history
- [x] 5.3 Manual test: ask the same question twice consecutively → verify only one history entry
- [x] 5.4 Manual test: submit 200+ questions → verify oldest entries are evicted
- [x] 5.5 Manual test: login as user A, submit questions → logout → login as user B → verify no cross-user history leak
- [x] 5.6 Manual test: close and reopen browser tab → verify history persists from localStorage
