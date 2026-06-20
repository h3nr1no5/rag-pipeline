## Context

The chat page (`client/pages/3_💬_Chat.py`) uses Streamlit's `st.chat_input` for question entry. This widget provides no built-in history navigation — no way to recall previous questions via arrow keys.

The application already stores query history server-side in `QueryCache` (via `GET /query/history`), but this is a response cache, not a question log. It deduplicates identical queries and expires after 3 days. The history page reads from it for display purposes.

This feature is purely frontend: localStorage-based question history with shell-style keyboard navigation.

## Goals / Non-Goals

**Goals:**
- Shell-style up/down arrow navigation through previously asked questions
- Question history persisted in browser localStorage across sessions
- Per-user isolation via user-ID-scoped localStorage key
- Consecutive duplicate suppression (same question asked twice in a row = one entry)
- Max 200 entries to stay well within localStorage's ~5MB limit

**Non-Goals:**
- Server-side storage of question history (QueryCache remains a response cache)
- Cross-device history sync
- Search/filter through history (flat arrow navigation only)
- Modifying the History page or any other page
- Changes to the backend API or database

## Decisions

1. **localStorage over session state persistence**
   - Session state is lost on tab close; localStorage survives browser restarts
   - localStorage is scoped per origin, shared across tabs — history available everywhere in the same browser
   - 200 questions × ~100 bytes ≈ 20KB — trivial for the 5MB limit

2. **User-ID-scoped key over global key**
   - Key format: `rag_question_history_{user_id_hash}`
   - On logout, the existing `logout()` function clears the current user's history key
   - On login, the page loads with the new user's history automatically (different key)
   - User ID hash is a short prefix of the UUID (first 8 chars) — enough for isolation without exposing the full ID

3. **Client-side only over adding a backend endpoint**
   - No new API surface, no DB migration, no new model
   - The feature is fundamentally a frontend UX enhancement
   - Server-side history would add latency on every page load and create data management concerns (retention, deletion, GDPR)

4. **`unsafe_allow_html` over custom Streamlit component**
   - Avoids adding an npm project + build step for a ~50-line JS handler
   - The same injection pattern is already used in Chat.py for auto-focus (lines 425-437)
   - Risk is mitigated by `json.dumps()` which properly escapes user content

5. **Terminal-style over dropdown/search**
   - Flat up/down cycling matches the user's stated preference and is the most familiar UX pattern
   - No UI chrome needed — no visible history widget, no click targets

## Risks / Trade-offs

- **[Security] User question text is injected into innerHTML via `unsafe_allow_html=True`** → Mitigation: `json.dumps()` provides standard JSON string escaping. Questions are user-typed text (not markdown or HTML from untrusted sources). The existing auto-focus script sets the same-risk precedent. Still, this is a security review requirement.

- **[Cross-user leak] localStorage is per-origin, not per-user** → Mitigation: User-ID-scoped key. On logout, the key is explicitly removed. Two users on the same browser with overlapping sessions (e.g., switching tabs) will each see only their own history.

- **[History staleness] History from the old chat_params.json file is unaffected** → No risk: `chat_params.json` stores temperature/top-k sliders, not question text. Independent feature.

- **[Streamlit DOM changes] The JS relies on `input[data-testid="stChatInputInput"]` selector** → Mitigation: Adding a fallback selector (`.stChatInput input`) and a retry loop with `setTimeout`. Streamlit rarely changes these test IDs across minor versions.

- **[No sync across devices] History is per-browser** → Acceptable: This is a convenience feature, not a data-critical one. Power users who need cross-device history can use the server-side `/query/history` page.
