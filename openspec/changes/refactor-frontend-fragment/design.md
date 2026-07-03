## Context

The current Chat.py (1027 lines) uses an async task polling pattern:

1. User submits question → `POST /query/start` creates a background task
2. Session state flags (`task_started`, `active_task_id`) are set
3. `st.rerun()` triggers a full page rerun
4. `poll_query_task()` is called at the bottom of the page (line 866)
5. Inside: polls `GET /query/status/{task_id}` every 1s via `time.sleep(1.0) + st.rerun()`
6. As backends complete, results are rendered inline AND persisted to session state with sentinel flags
7. On completion: safety net catches any missed answers, then `st.rerun()` clears the "in progress" UI

**The bug**: `st.rerun()` on completion (line 763) stops execution mid-stream. On the next run, the message loop at line 462 renders messages from session state. If a rerun interrupts between persisting a result and rendering it, that answer is invisible on that pass. The safety net (lines 699-751) mitigates but doesn't eliminate this — it uses sentinel flags (`answer_stored_*`) to catch missed answers, but the sentinel flags themselves are set at different times than the message append, creating a window for inconsistency.

**The solution**: `@st.fragment(run_every=1.0)` scopes polling reruns to the polling section only. The message loop and sidebar never re-execute during polling, eliminating the race condition entirely. Fragment state is stable across its own reruns, removing the need for sentinel flags and the safety net.

## Goals / Non-Goals

**Goals:**
- Fix the "answers not showing" bug by eliminating full-page reruns during polling
- Wrap polling logic in `@st.fragment(run_every=1.0)` for scoped, auto-rerunning polls
- Remove all `rendered_*` and `answer_stored_*` sentinel flags
- Remove the 50-line completion safety net
- Remove `query_polling_done` and simplify `active_query_params`
- Keep backend async infrastructure (task manager, endpoints) fully intact
- Keep `async_query_start()` and `async_query_poll()` in `query.py` unchanged

**Non-Goals:**
- No changes to backend task manager or query endpoints
- No changes to the sync query approach or its endpoints
- No changes to model warmup polling (lines 122-206)
- No changes to document selection, sidebar, or parameter UI
- No changes to `client/utils/query.py` — helpers stay exactly as they are
- No reduction in functionality — same user experience, fewer internal states

## Decisions

### Decision 1: Fragment scope — polling section only
**Choice**: `@st.fragment(run_every=1.0)` wraps only the polling logic (currently lines 516-781).
**Rationale**: The fragment needs to render progress indicators (counts, per-backend spinners) and inline results. These are already bundled in `poll_query_task()`. Keeping the message loop (lines 462-513) and sidebar outside the fragment means they never re-execute during polling — stable UI, no race conditions.
**Alternatives considered**: Wrapping the entire page in a fragment would defeat the purpose (full rerun still happens). Wrapping only the progress counter (not inline rendering) would make the fragment too narrow — inline results wouldn't appear until completion.

### Decision 2: Auto-rerun via fragment, not `time.sleep() + st.rerun()`
**Choice**: `@st.fragment(run_every=1.0)` replaces all `time.sleep(1.0)` and `st.rerun()` calls inside the polling logic.
**Rationale**: The fragment decorator provides built-in periodic rerun. When `task_started` is `True`, the fragment re-executes every 1s. When `task_started` becomes `False` (completion or error), the fragment returns without rerunning. No manual `st.rerun()` needed — Streamlit handles the schedule.
**Alternatives considered**: Keeping `time.sleep() + st.rerun()` but inside a fragment — worse because it mixes two rerun mechanisms. Removing fragments entirely would leave the original bug unfixed.

### Decision 3: Remove sentinel flags and safety net
**Choice**: Delete all `rendered_*` and `answer_stored_*` tracking. Delete the safety net (lines 699-751).
**Rationale**: Sentinel flags existed to prevent double-rendering across reruns. Since the fragment provides a stable scope, the same result is never rendered twice. The safety net existed to catch answers missed by rerun interruptions — with scoped reruns, interruptions can't happen.
**Risk**: Low. The fragment's stable scope guarantees that each poll response is processed exactly once per state change. If the fragment encounters a backend result it hasn't rendered, it renders it. No dedup needed.

### Decision 4: Keep `async_query_start()` and `async_query_poll()` unchanged
**Choice**: Both helper functions in `client/utils/query.py` remain exactly as they are.
**Rationale**: The async polling pattern stays — only the frontend driver mechanism changes. The helpers are well-tested and provide clean error handling and logging. Removing them would require rewriting the backend interaction layer, which is out of scope.
**Alternatives considered**: Switching to sync endpoints — previously explored and blocked by Streamlit rendering model limitations.

### Decision 5: Simplify session state — remove `query_polling_done`, keep `task_started` and `active_task_id`
**Choice**: `query_polling_done` is removed (it was only checked by the safety net). `active_query_params` is simplified — params can be read from the sidebar widgets directly instead of snapshotting them at query start.
**Rationale**: With fragment-based polling, we only need to know "is there an active task?" (`task_started`) and "which task?" (`active_task_id`). The params snapshot was needed because full-page reruns could change widget values — with the fragment scoped, widget values are stable. However, to minimize change scope, we can keep `active_query_params` as-is and defer its removal to a future cleanup.
**Risk**: Removing `active_query_params` requires reading sidebar widgets from inside the fragment. Since the sidebar is outside the fragment, widget values are accessible but may cause subtle issues. To be safe, keep `active_query_params` snapshotting as-is for now.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| [Fragment not supported in older Streamlit] Feature unavailable | Users on Streamlit <1.33 can't use the fix | Check `st.rerun_scope` availability; fall back to current behavior. However, the project already depends on Streamlit features from 1.35+. |
| [Fragment runs after task completes] Extra poll after completion | One unnecessary GET request | The fragment checks `task_started` at the top. On the rerun after completion, it sees `False` and returns immediately. The cost is one extra fragment execution — negligible. |
| [Fragment re-renders results on each poll] Duplicate inline rendering | Blinking UI during polling | Keys/IDs ensure stable rendering. The fragment only renders results it hasn't seen before — new backends appear inline without re-rendering old ones. |
| [Safety net removal misses edge case] Answer not rendered | User sees fewer answers | The safety net was a workaround for the rerun race condition. With scoped reruns, the race condition doesn't exist. If a backend completes between fragment executions, it'll be picked up on the next fragment poll. |
