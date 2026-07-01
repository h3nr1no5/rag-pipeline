## 1. Backend: TaskManager Service

- [ ] 1.1 Create `src/domain/services/task_manager.py` with `TaskRecord` dataclass and `TaskManager` class
  - `TaskRecord` fields: `task_id`, `user_id`, `status`, `created_at`, `updated_at`, `progress`, `result`, `error`, `_task`
  - `TaskManager` methods: `create()`, `get()`, `cancel()`, `cancel_all()`, `_cleanup()`
  - Use `asyncio.Lock` for thread-safe dict access
  - Periodic cleanup: remove tasks older than 15 minutes (completed/cancelled/error only)
  - Cap at 1000 entries, evict oldest

- [ ] 1.2 Add cleanup lifecycle hook to `src/api/main.py`
  - Wire `TaskManager.cleanup()` into the FastAPI lifespan
  - Run cleanup every 60 seconds

- [ ] 1.3 Add shutdown task cancellation to `src/api/main.py` lifespan
  - On shutdown event, call `task_manager.cancel_all()`
  - This cancels all active `asyncio.Task` objects
  - Do NOT await task completion — shutdown proceeds immediately
  - Orphan GPU threads will continue but results are discarded

## 2. Backend: Task Query API Endpoints

- [ ] 2.1 Add request/response schemas to `src/api/schemas/query.py`
  - `TaskCreateResponse`: `task_id: str`
  - `TaskStatusResponse`: `status`, `progress`, `result?`, `error?`
  - `TaskCancelResponse`: `status`

- [ ] 2.2 Add `POST /api/v1/query/start` endpoint in `src/api/routes/query/routes.py`
  - Accept same payload as existing `POST /api/v1/query`
  - Create background `asyncio.Task` via TaskManager
  - Return HTTP 201 with `task_id`
  - Require JWT auth (full `get_current_user()`)

- [ ] 2.3 Add `GET /api/v1/query/status/{task_id}` endpoint
  - Lightweight auth: `decode_access_token()` only (no DB lookup)
  - Validate task ownership (`task.user_id == token.sub`)
  - Return task status + result if completed
  - Return 404 if task not found, 403 if unauthorized

- [ ] 2.4 Add `POST /api/v1/query/cancel/{task_id}` endpoint
  - Full JWT auth + ownership check
  - Call `asyncio.Task.cancel()` on the running task
  - Return updated status
  - No-op if task is already completed

## 3. Backend: Background Task Execution Logic

- [ ] 3.1 Create `_execute_rag_query()` async function that runs the full RAG pipeline
  - Create its own `AsyncSession` via `async_session_maker()`
  - Execute selected RAG backends sequentially (cosine → langchain → llamaindex)
  - If API Docs is selected, run it as a 4th sequential step after all RAG backends
  - API Docs query uses the internal Python function (not a separate HTTP call)
  - Accept explicit `user_id` parameter for data isolation in all DB queries
  - Update progress text between backends (e.g., "Answer 1 of 3 complete...", "Processing API Documentation...")
  - Handle `asyncio.CancelledError` → mark as cancelled
  - Handle all other exceptions → mark as error
  - Store final result in TaskManager

- [ ] 3.2 Refactor existing query pipeline logic from routes.py into a reusable async function
  - Extract the core RAG query logic (retrieval → dedup → prompt → LLM → verify → clean)
  - Make it callable both from the sync route and the background task
  - Background task creates its own `AsyncSession` via `async_session_maker()` (not the request's session)
  - Accept explicit `user_id` parameter for data isolation across all DB queries

- [ ] 3.4 Refactor API Docs query into a callable function from the background task
  - Extract the API Docs query logic (currently only in `api_docs_query()` HTTP helper)
  - Make it callable internally with a `user_id` and `doc_id` parameter
  - No separate HTTP request needed when called from background task

- [ ] 3.3 Verify `asyncio.Lock` behavior on cancellation
  - Test that `CancelledError` during `self._generate_lock` context manager properly releases the lock
  - If lock is not released, add try/finally to guarantee release

## 4. Frontend: Polling-Based Query Flow

- [ ] 4.1 Add `async_query_start()`, `async_query_poll()`, `async_query_cancel()` helper functions
  - `async_query_start()`: POST to `/api/v1/query/start`, return task_id
  - `async_query_poll()`: GET `/api/v1/query/status/{task_id}`, return status dict
  - `async_query_cancel()`: POST `/api/v1/query/cancel/{task_id}`, return updated status
  - Handle 401 by redirecting to login, 404 by showing "session expired"

- [ ] 4.2 Replace ThreadPoolExecutor + as_completed() block (lines 534-616) with task polling
  - On submit: call `async_query_start()`, store `task_id` in `st.session_state.active_task_id`, `st.rerun()`
  - On rerun with `active_task_id`: enter a `time.sleep()` polling loop (follow model-warmup pattern at Chat.py:126-190)
  - Inside loop: call `async_query_poll()`, update spinner/progress text, `time.sleep(2)`, repeat
  - Do NOT call `st.rerun()` on every poll iteration — only sidebar/document logic runs once per rerun
  - If `status == "completed"`: render result, clear `active_task_id`, `st.rerun()` to refresh message list
  - If `status == "error"`: show error, clear `active_task_id`
  - If `status == "cancelled"`: show "Cancelled" message, clear `active_task_id`
  - If HTTP 404: show "Query session expired — please retry", clear `active_task_id`

- [ ] 4.3 Add cancel button UI during processing
  - Show `st.button("Cancel")` when status is "processing"
  - On click: call `async_query_cancel()`, set `st.session_state.cancelling = True`
  - On poll with `cancelling = True`, wait for confirmed "cancelled" status

- [ ] 4.4 Disable chat input while task is active
  - Set `st.chat_input(disabled=True)` when `active_task_id` is set
  - Check for existing task before creating a new one (prevent rapid resubmit)
  - If `active_task_id` exists and user tries to submit, cancel previous task first

- [ ] 4.5 Add cancel semantics documentation in UI
  - Cancel button shows "Cancelling — finishing current operation..." while in progress
  - After confirmed: show "Query cancelled. Completed backends are shown above."
  - Partial results from completed backends remain visible

## 5. Fix Max Tokens Schema & Frontend Bounds

- [ ] 5.1 Update `src/api/schemas/query.py` max_tokens field
  - Change `le=2000` to `le=1200`
  - Keep `default=600`, `ge=50`

- [ ] 5.2 Update frontend max_tokens slider in `Chat.py`
  - Change `max_value=4096` to `max_value=1200`
  - Change `value=saved_params.get("max_tokens", 2048)` to `value=saved_params.get("max_tokens", 600)`

- [ ] 5.3 Add safe migration for saved max_tokens values
  - When loading saved params from `chat_params.json`, clamp `max_tokens` to `min(value, 1200)`
  - Do NOT show validation error for previously saved values above 1200
  - Log a warning when clamping occurs

## 6. Unit Tests

- [ ] 6.1 Write `tests/unit/test_task_manager.py`
  - `test_create_get_cancel` — full lifecycle
  - `test_cleanup_expired_tasks` — old tasks removed
  - `test_cleanup_cap` — 1000 entry cap enforced
  - `test_cancel_completed_is_noop`
  - `test_task_manager_thread_safety` — concurrent reads/writes
  - `test_ownership_isolation` — tasks scoped by user_id

- [ ] 6.2 Write `tests/unit/test_query_schemas.py`
  - `test_max_tokens_bounds` — 1200 max, 50 min, 600 default
  - `test_task_create_response_schema`
  - `test_task_status_response_schema`

- [ ] 6.3 Extend `cancel_background_tasks` fixture in conftest.py
  - Add query task name prefix (`query_rag_`) to the list of tasks cancelled between tests
  - Ensure background query tasks from one test don't leak into the next test
  - Verify fixture works with `setup_test_db` (autouse conftest fixture)

## 7. Integration Tests

- [ ] 7.1 Write `tests/integration/test_async_query.py`
  - `test_async_query_lifecycle` — start → poll → complete (mock LLM)
  - `test_async_query_cancel_during_processing` — cancel mid-flight
  - `test_async_query_requires_auth` — 401 without token
  - `test_async_query_ownership` — user B can't access user A's task
  - `test_async_query_error_propagation` — LLM error stored as task error
  - `test_async_query_backward_compatibility` — existing POST /query still works
  - `test_async_query_double_submit` — rapid clicks create single task (race condition)
  - `test_async_query_poll_during_queued` — poll between "queued" and "processing" states
  - `test_async_query_close_and_api_docs` — mixed RAG + API Docs query
  - `test_async_query_max_tokens_clamping` — saved value >1200 is clamped on load

## 8. Verify

- [ ] 8.1 Run full test suite excluding slow: `uv run pytest -v -m "not slow"`
- [ ] 8.2 Run integration tests: `uv run pytest tests/integration/ -v`
- [ ] 8.3 Run linting: `uv run ruff check .`
- [ ] 8.4 Run type checking: `uv run mypy src/`
- [ ] 8.5 Manual smoke test: submit a query, verify spinner shows, result appears, cancel works
