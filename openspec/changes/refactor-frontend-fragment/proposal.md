## Why

The async task polling pattern (added in `fix-rag-ui-freeze`) introduces a rerun race condition: when `poll_query_task()` calls `st.rerun()` on task completion, execution stops mid-stream, and the next run's message rendering loop (line 462) can be interrupted before it displays answers that were already stored in session state. This causes the "answers not showing" bug. Additionally, the 265-line polling function uses 4 sentinel flags (`rendered_*`, `answer_stored_*`), a 50-line safety net for missed answers, and explicit `time.sleep(1.0) + st.rerun()` cycling — all of which add complexity without solving the core rendering reliability issue.

The fix is to scope polling reruns to the polling section only using `@st.fragment(run_every=1.0)`. This eliminates full-page rerun storms, keeps the message loop and sidebar stable, and removes the need for sentinel flags and safety nets entirely.

## What Changes

1. **Simplify Chat.py polling with `@st.fragment`**: Wrap the polling logic in a `@st.fragment(run_every=1.0)` function. The fragment auto-reruns at 1s intervals while a task is active, eliminating `time.sleep() + st.rerun()` cycling.
2. **Remove sentinel flags**: The `rendered_*` and `answer_stored_*` sentinel flags become unnecessary — fragments maintain stable state across reruns.
3. **Remove safety net**: The 50-line completion safety net (lines 699-751) is no longer needed since the message loop is never interrupted.
4. **Remove explicit `st.rerun()` on completion**: The fragment auto-reruns; when the task completes and `task_started` flips to `False`, the fragment stops naturally.
5. **Simplify progress rendering**: Progress indicators render within the fragment's stable scope — no placeholder management needed.
6. **Reduce session state variables**: `query_polling_done` and `active_query_params` can be removed or simplified.
7. **Keep async infrastructure intact**: Backend task manager, `/query/start`, `/query/status`, `async_query_start()`, and `async_query_poll()` all remain unchanged.

## Capabilities

### New Capabilities
- `frontend-fragment-polling`: Streamlit `@st.fragment(run_every=1.0)`-based polling for async query task status. Scoped reruns, no full-page interruption, no sentinel flags.

### Modified Capabilities
- `frontend-loading-indicators`: Requirements change from the old ThreadPoolExecutor concurrent dispatch pattern to the new fragment-based polling pattern. Per-backend progress indicators now render within a fragment's stable scope instead of needing placeholder management. The completion mechanism changes from `st.rerun()` to fragment natural termination.

## Impact

| Area | Change |
|------|--------|
| `client/pages/3_💬_Chat.py` | Replace 265-line `poll_query_task()` with compact `@st.fragment` function. Remove sentinel flags, safety net, and explicit reruns. ~150 lines removed. |
| `client/utils/query.py` | No changes — `async_query_start()` and `async_query_poll()` remain in use |
| `src/api/` (backend) | No changes — task manager, endpoints, and all performance fixes stay intact |
| `openspec/specs/frontend-loading-indicators/spec.md` | Updated from ThreadPoolExecutor to fragment-based polling |
