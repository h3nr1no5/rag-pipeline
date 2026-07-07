## 1. Fragment — Wrap Polling Logic in `@st.fragment(run_every=1.0)`

- [x] 1.1 Add `from streamlit import fragment` import at the top of Chat.py
- [x] 1.2 Wrap `poll_query_task()` with `@st.fragment(run_every=1.0)` decorator — placed immediately before `def poll_query_task():`
- [x] 1.3 Remove all `time.sleep(1.0)` calls inside `poll_query_task()` — the fragment's built-in rerun schedule replaces manual sleep
- [x] 1.4 Remove all `st.rerun()` calls inside `poll_query_task()` — the fragment's auto-rerun replaces explicit reruns
  - Lines to change: line 763 (`st.rerun()` on completed), line 781 (`st.rerun()` on still-running), line 560 (`st.rerun()` on error cleanup)
  - On error cleanup (line 560): change to `return` instead of `st.rerun() + return`
  - On completion (line 757-763): change to set state flags and `return` instead of `st.rerun()`
- [x] 1.5 Verify the `time.sleep(1.0)` at line 780 (still-running branch) is replaced by the fragment's 1s auto-rerun — change to a simple `return`
- [x] 1.6 Ensure the fragment still appends results to `st.session_state.messages` (persistence for cross-session survival)

## 2. Fragment — Remove Sentinel Flags and Safety Net

- [x] 2.1 Delete all `cache_key = f"rendered_{task_id}_{r['backend']}"` lines and their usage (progressive rendering section, lines ~600-651)
- [x] 2.2 Delete all `answer_stored_key = f"answer_stored_{task_id}_{r['backend']}"` lines and their usage
- [x] 2.3 Delete the safety net block (lines ~699-751) — the completion handler that catches missed answers with sentinel flags
- [x] 2.4 Simplify the per-backend result rendering: check `st.session_state.messages` for existing entries of that backend+task instead of using sentinel flags; or use a simpler "has this backend result been appended?" check

## 3. Fragment — Simplify Session State

- [x] 3.1 Remove `query_polling_done` initialization (line 139-140) and all references throughout Chat.py
  - Line 139-140: `if "query_polling_done" not in st.session_state: st.session_state.query_polling_done = True`
  - Line 559: `st.session_state.query_polling_done = True`
  - Line 684: `st.session_state.query_polling_done = True`
  - Line 760: `st.session_state.query_polling_done = True`
  - Line 776: `st.session_state.query_polling_done = True`
  - Line 877: `st.session_state.query_polling_done = True`
- [x] 3.2 Verify `active_task_id` and `task_started` remain — these are still needed for fragment-driven activation
- [x] 3.3 Keep `active_query_params` as-is (deferred cleanup per design.md Decision 5)

## 4. Fragment — Clean Up Imports

- [x] 4.1 Remove `import time` from the top of Chat.py if `time` is no longer referenced elsewhere
- [x] 4.2 Remove `from client.utils.query import async_query_poll, async_query_start` if these move — **Note**: they should stay since the fragment still calls them. Verify imports are correct.

## 5. Specs — Sync Delta Specs to Main Specs

- [x] 5.1 Sync delta spec `frontend-loading-indicators/spec.md` → `openspec/specs/frontend-loading-indicators/spec.md`
- [x] 5.2 Create new main spec `openspec/specs/frontend-fragment-polling/spec.md`

## 6. Verify

- [x] 6.1 Run `uv run ruff check client/pages/3_💬_Chat.py` — no lint errors
- [x] 6.2 Run `uv run mypy client/pages/3_💬_Chat.py` — no type errors (or no new ones)
- [x] 6.3 Run `uv run pytest tests/unit/ -v` — all unit tests pass
- [ ] 6.4 Start backend (`uvicorn src.api.main:app --port 8000`) and frontend (`streamlit run client/app.py --server.port 8501`) — verify query works, answers render reliably after polling completes
- [ ] 6.5 Test the "answers not showing" scenario: submit a question with 3 backends, verify all 3 answers appear after completion without requiring a page refresh
