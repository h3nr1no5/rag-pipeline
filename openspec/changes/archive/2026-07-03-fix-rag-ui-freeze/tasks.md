## 1. Backend: TaskManager Service

- [x] 1.1 Create `src/domain/services/task_manager.py` with `TaskRecord` and `BackendResult` dataclasses and `TaskManager` class
  - `BackendResult` fields: `backend`, `status`, `answer?`, `sources?`, `latency_ms?`, `error?`, `rag_type?`
  - `TaskRecord` fields: `task_id`, `user_id`, `status`, `created_at`, `updated_at`, `progress`, `results: list[BackendResult]`, `error?`, `_task`
  - `TaskManager` methods: `create()`, `get()`, `_cleanup()`
  - Use `asyncio.Lock` for thread-safe dict access
  - Periodic cleanup: remove tasks older than 15 minutes (completed/error only)
  - Cap at 1000 entries, evict oldest

- [x] 1.2 Add cleanup lifecycle hook to `src/api/main.py`
  - Wire `TaskManager.cleanup()` into the FastAPI lifespan
  - Run cleanup every 60 seconds

## 2. Backend: Task Query API Endpoints

- [x] 2.1 Add request/response schemas to `src/api/schemas/query.py`
  - `TaskCreateResponse`: `task_id: str`
  - `BackendResultSchema`: `backend`, `status`, `answer?`, `sources?`, `latency_ms?`, `error?`, `rag_type?`
  - `TaskStatusResponse`: `status`, `progress`, `results: list[BackendResultSchema]`, `error?`

- [x] 2.2 Add `POST /api/v1/query/start` endpoint in `src/api/routes/query/routes.py`
  - Accept same payload as existing `POST /api/v1/query`
  - Create background `asyncio.Task` via TaskManager
  - Return HTTP 201 with `task_id`
  - Require JWT auth (full `get_current_user()`)

- [x] 2.3 Add `GET /api/v1/query/status/{task_id}` endpoint
  - Lightweight auth: `decode_access_token()` only (no DB lookup)
  - Validate task ownership (`task.user_id == token.sub`)
  - Return task status + result if completed
  - Return 404 if task not found, 403 if unauthorized

## 3. Backend: Background Task Execution Logic

- [x] 3.1 Create `_execute_rag_query()` async function that runs the full RAG pipeline
  - Create its own `AsyncSession` via `async_session_maker()`
  - Dispatch retrieval phases concurrently via `asyncio.gather()` across selected RAG backends
  - Wrap each backend in an `_execute_backend()` sub-task that: retrieves → awaits LLM lock → generates → writes to `TaskRecord.results[]`
  - Because LLM generation is serialized by `asyncio.Lock`, each sub-task automatically waits for its turn
  - If API Docs is selected, run it as a sequential step after all `gather()` sub-tasks complete
  - API Docs query uses the internal Python function (not a separate HTTP call)
  - Accept explicit `user_id` parameter for data isolation in all DB queries
  - Update progress text and `results[]` between backends (e.g., "Answer 1 of 3 complete...", "Processing API Documentation...")
  - Handle individual backend exceptions → mark that backend as `status: "error"` in `results[]`, continue others
  - Store final results array in TaskManager

- [x] 3.2 Refactor existing query pipeline logic from routes.py into a reusable async function
  - Extract the core RAG query logic (retrieval → dedup → prompt → LLM → verify → clean)
  - Make it callable both from the sync route and the background task
  - Background task creates its own `AsyncSession` via `async_session_maker()` (not the request's session)
  - Accept explicit `user_id` parameter for data isolation across all DB queries

- [x] 3.3 Refactor API Docs query into a callable function from the background task
  - Extract the API Docs query logic (currently only in `api_docs_query()` HTTP helper)
  - Make it callable internally with a `user_id` and `doc_id` parameter
  - No separate HTTP request needed when called from background task

- [x] 3.4 Update TaskRecord schema to use `results: list[BackendResult]` instead of `result: dict | None`
  - `BackendResult` dataclass: `backend`, `status`, `answer?`, `sources?`, `latency_ms?`, `error?`, `rag_type?`
  - Each sub-task writes its `BackendResult` to the shared `results[]` list as it completes
  - Ensure thread-safe append (use the existing `asyncio.Lock` or a dedicated list lock)

## 4. Frontend: Fragment-Scoped Polling Query Flow

- [x] 4.1 Add `async_query_start()` and `async_query_poll()` helper functions
  - `async_query_start()`: POST to `/api/v1/query/start`, return task_id
  - `async_query_poll()`: GET `/api/v1/query/status/{task_id}`, return status dict
  - Handle 401 by redirecting to login, 404 by showing "session expired"
  - Handle network errors by raising a typed exception (caller retries)

- [x] 4.2 Create `@st.fragment`-decorated polling function
  - Guard at top: `if st.session_state.get("query_polling_done"): return`
  - Poll `GET /api/v1/query/status/{task_id}` for current status
  - Show progress text via `st.markdown()` (NOT `st.spinner()`, which can't persist across reruns)
  - Use `st.rerun(scope="fragment")` for scoped reruns (NOT full-page `st.rerun()`)
  - The fragment SHALL receive or access `task_id` from `st.session_state.active_task_id`

- [x] 4.3 Replace ThreadPoolExecutor + as_completed() block (lines 534-616) with fragment-based flow
  - On submit: cache doc list, store `task_id` in `st.session_state.active_task_id`, reset `query_polling_done`, call `st.rerun()`
  - The fragment (4.2) drives the polling loop — non-blocking to the rest of the page
  - On `"processing"` with completed entries in `results[]`: render completed results progressively
  - On `"completed"`: render all results, clear session state, set `query_polling_done = True`, `st.rerun(scope="fragment")`
  - On `"error"`: render completed results + error for failures, clear session state
  - On HTTP 404: show "Query session expired — please retry", clear session state
  - Remove all `ThreadPoolExecutor` imports, `as_completed()`, `future.result()` usage

- [x] 4.4 Add per-backend progressive rendering to fragment
  - When `results[]` contains completed entries during processing, render them with correct avatar and formatting
  - For entries with `backend: "api_docs"`, use API Docs-specific rendering (confidence badges, reasoning expander, relevant functions/types)
  - For standard RAG backends, use existing per-backend chat message format
  - Show per-backend loading indicators for entries still `"processing"` or `"queued"`

- [x] 4.5 Add document list caching during polling
  - On submit: save `st.session_state._cached_doc_list` and `_cached_doc_statuses`
  - During polling: sidebar reads from cache instead of making API calls
  - On completion/error/404: clear cached values

- [x] 4.6 Add network error handling with retry
  - Catch `requests.ConnectionError`, `Timeout`, HTTP 5xx during poll
  - Retry up to 3 times with 5-second backoff between attempts
  - If all retries exhausted: show "Connection lost — please check your connection", show "Retry Now" button
  - Do NOT clear `active_task_id` on network errors (task continues on server)

- [x] 4.7 Add loading state on initial submit
  - Show "Creating query..." indicator immediately when submit is pressed (before POST)
  - Transition to polling progress display once POST returns `task_id`
  - Show error if POST fails (network error, 500)

- [x] 4.8 Add `models_ready` interaction handling during polling
  - If `models_ready` becomes `False` during active query: show warning, continue polling
  - Model-warmup block should not re-trigger model download during active query
  - Ensure `active_task_id` persists across model state changes

- [x] 4.9 Disable inputs while task is active
  - Set `st.chat_input(disabled=True)` when `active_task_id` is set
  - Disable "Clear Chat" button during active query
  - Disable sidebar parameter widgets (temperature, top_k, selected backends) during active query
  - Check for existing task before creating a new one (prevent rapid resubmit)

## 5. Fix Max Tokens Schema & Frontend Bounds

- [x] 5.1 Update `src/api/schemas/query.py` max_tokens field
  - Change `le=2000` to `le=1200`
  - Keep `default=600`, `ge=50`

- [x] 5.2 Update frontend max_tokens slider in `Chat.py`
  - Change `max_value=4096` to `max_value=1200`
  - Change `value=saved_params.get("max_tokens", 2048)` to `value=saved_params.get("max_tokens", 600)`

- [x] 5.3 Add safe migration for saved max_tokens values
  - When loading saved params from `chat_params.json`, clamp `max_tokens` to `min(value, 1200)`
  - Do NOT show validation error for previously saved values above 1200
  - Log a warning when clamping occurs

## 6. Unit Tests

- [x] 6.1 Write `tests/unit/test_task_manager.py`
  - `test_create_get` — full lifecycle
  - `test_cleanup_expired_tasks` — old tasks removed
  - `test_cleanup_cap` — 1000 entry cap enforced
  - `test_task_manager_thread_safety` — concurrent reads/writes
  - `test_ownership_isolation` — tasks scoped by user_id

- [x] 6.2 Write `tests/unit/test_query_schemas.py`
  - `test_max_tokens_bounds` — 1200 max, 50 min, 600 default
  - `test_task_create_response_schema`
  - `test_task_status_response_schema`
  - `test_backend_result_schema` — per-backend entry in results[] validates correctly
  - `test_partial_results_format` — mixed completed/processing/error entries
  - `test_api_docs_result_entry` — rag_type field included for api_docs backend

- [x] 6.3 Extend `cancel_background_tasks` fixture in conftest.py
  - Add query task name prefix (`query_rag_`) to the list of tasks cancelled between tests
  - Ensure background query tasks from one test don't leak into the next test
  - Verify fixture works with `setup_test_db` (autouse conftest fixture)

## 7. Integration Tests

- [x] 7.1 Write `tests/integration/test_async_query.py`
  - `test_async_query_lifecycle` — start → poll → complete (mock LLM)
  - `test_async_query_requires_auth` — 401 without token
  - `test_async_query_ownership` — user B can't access user A's task
  - `test_async_query_error_propagation` — LLM error stored as task error
  - `test_async_query_backward_compatibility` — existing POST /query still works
  - `test_async_query_double_submit` — rapid clicks create single task (race condition)
  - `test_async_query_poll_during_queued` — poll between "queued" and "processing" states
  - `test_async_query_close_and_api_docs` — mixed RAG + API Docs query
  - `test_async_query_max_tokens_clamping` — saved value >1200 is clamped on load
  - `test_async_query_partial_results` — poll returns partial results[] while processing
  - `test_async_query_per_backend_error_isolation` — one backend fails, others complete
  - `test_async_query_concurrent_retrieval` — verify retrieval phases overlap in time (not sequential)
  - `test_async_query_fragment_polling` — verify fragment-scoped rerun behavior (mock st.rerun scope)
  - `test_async_query_network_retry` — simulate transient network error, verify retry logic
  - `test_async_query_doc_cache` — verify document list not re-fetched during active query

## 8. Verify

- [x] 8.0 Verify `pyproject.toml` specifies Streamlit >= 1.33 (required for `st.fragment`)
- [x] 8.1 Run full test suite excluding slow: `uv run pytest -v -m "not slow"`
- [x] 8.2 Run integration tests: `uv run pytest tests/integration/ -v`
- [x] 8.3 Run linting: `uv run ruff check .`
- [x] 8.4 Run type checking: `uv run mypy src/`
- [x] 8.5 Manual smoke test: submit a query, verify:
  - Spinner shows with progress text
  - Chat history remains scrollable during query
  - Sidebar parameters not adjustable during query
  - Result appears after completion
  - Each backend result renders with correct avatar
  - API Docs result (if selected) shows confidence badges and reasoning
  - "Clear Chat" button is disabled during query
  - Network disconnection shows retry option
