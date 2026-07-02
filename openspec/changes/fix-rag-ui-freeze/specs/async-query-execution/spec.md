# Async Query Execution

## Purpose

Enable long-running RAG queries to execute as background tasks, keeping the Streamlit UI fully responsive via polling. Provide task lifecycle management: create and poll status.

## ADDED Requirements

### Requirement: Backend SHALL provide task creation endpoint

The backend SHALL expose `POST /api/v1/query/start` that accepts the same payload as the existing `POST /api/v1/query` endpoint plus a `task_id` response. The endpoint SHALL return immediately (HTTP 201) with a unique task ID. The actual RAG query SHALL execute as a background `asyncio.Task`.

#### Scenario: Task created successfully
- **WHEN** a user sends a valid query payload to `POST /api/v1/query/start`
- **THEN** the endpoint SHALL respond with HTTP 201
- **THEN** the response SHALL contain `{"task_id": "<uuid>"}`
- **THEN** the task SHALL be registered in the TaskManager with `status: "queued"`
- **THEN** the task SHALL begin executing immediately (transition to `"processing"`)

#### Scenario: Task creation with invalid payload
- **WHEN** a user sends an invalid query payload (empty question, missing auth)
- **THEN** the endpoint SHALL respond with the same validation errors as `POST /api/v1/query`
- **THEN** no task SHALL be created

#### Scenario: Authentication required
- **WHEN** a request is made without a valid JWT token
- **THEN** the endpoint SHALL respond with HTTP 401
- **THEN** no task SHALL be created

### Requirement: Backend SHALL provide task status endpoint

The backend SHALL expose `GET /api/v1/query/status/{task_id}` that returns the current state of a task.

#### Scenario: Task is processing
- **WHEN** a task exists and is currently running
- **THEN** the response SHALL contain `{"status": "processing", "progress": "Answer 1 of 3 complete..."}`
- **THEN** no `result` field SHALL be present

#### Scenario: Task completed successfully
- **WHEN** a task has finished execution
- **THEN** the response SHALL contain `{"status": "completed", "progress": "Done", "result": {...}}`
- **THEN** the `result` SHALL contain the same structure as `POST /api/v1/query` response (answer, sources, latency_ms)

#### Scenario: Task completed with error
- **WHEN** a task encountered an error during execution
- **THEN** the response SHALL contain `{"status": "error", "progress": "LLM generation failed: ...", "result": null}`
- **THEN** the error message SHALL be descriptive

#### Scenario: Task not found
- **WHEN** the task ID does not exist (invalid ID, expired, or server restarted)
- **THEN** the endpoint SHALL respond with HTTP 404
- **THEN** the response SHALL contain `{"detail": "Task not found"}`

#### Scenario: Task ownership enforced
- **WHEN** User A requests the status of User B's task
- **THEN** the endpoint SHALL respond with HTTP 403
- **THEN** the task data SHALL NOT be exposed

#### Scenario: Lightweight auth for polling
- **WHEN** the status endpoint is called
- **THEN** the endpoint SHALL validate the JWT token via `decode_access_token()` (no DB lookup)
- **THEN** the endpoint SHALL compare `task.user_id` against `token.sub`
- **THEN** the endpoint SHALL NOT execute the full `get_current_user()` dependency

### Requirement: TaskManager SHALL auto-cleanup old tasks

The TaskManager SHALL periodically remove tasks that are no longer needed to prevent memory leaks.

#### Scenario: Periodic cleanup removes expired tasks
- **WHEN** a task has been completed or errored for more than 15 minutes
- **THEN** the cleanup routine SHALL remove it from the in-memory dict
- **THEN** subsequent status polls SHALL return HTTP 404

#### Scenario: Cleanup cap prevents unbounded growth
- **WHEN** the TaskManager dict exceeds 1000 entries
- **THEN** the oldest tasks SHALL be evicted first regardless of age
- **THEN** evicted tasks SHALL return HTTP 404 on status poll

### Requirement: Frontend SHALL use fragment-scoped polling instead of blocking HTTP

The chat page SHALL replace the existing `ThreadPoolExecutor` + `as_completed()` pattern with task creation + fragment-scoped polling. The frontend SHALL remain fully interactive during query execution.

#### Scenario: Submit creates task and begins polling
- **WHEN** a user submits a question
- **THEN** the frontend SHALL call `POST /api/v1/query/start` with the query parameters
- **THEN** the frontend SHALL cache the current document list and per-doc statuses in `st.session_state._cached_doc_list`
- **THEN** the returned `task_id` SHALL be stored in `st.session_state.active_task_id`
- **THEN** `st.session_state.query_polling_done` SHALL be reset to `False`
- **THEN** `st.rerun()` SHALL be called to enter the fragment

#### Scenario: Polling runs inside @st.fragment
- **WHEN** the page re-renders with `active_task_id` set
- **THEN** a `@st.fragment`-decorated function SHALL handle the polling loop
- **THEN** the fragment SHALL call `GET /api/v1/query/status/{task_id}` to get current status
- **THEN** the fragment SHALL show progress text via `st.markdown()` (NOT `st.spinner()`, which is a context manager and can't persist across reruns)
- **THEN** the fragment SHALL call `time.sleep(2)` between status checks
- **THEN** the fragment SHALL call `st.rerun(scope="fragment")` to re-run only the fragment (not the full page)
- **THEN** the rest of the page (sidebar, chat history, document list) SHALL NOT be re-executed during polling
- **THEN** the user SHALL be able to scroll the chat history during polling
- **THEN** the user SHALL be able to navigate to other pages during polling
- **THEN** the browser tab SHALL NOT show "not responding"

#### Scenario: Partial results rendered progressively
- **WHEN** `status` is `"processing"` and `results[]` contains completed entries
- **THEN** the fragment SHALL render each completed entry with its avatar and formatting
- **THEN** entries with `status: "processing"` or `"queued"` SHALL show a per-backend loading indicator
- **THEN** the fragment SHALL continue polling

#### Scenario: All results rendered on completion
- **WHEN** status returns `"completed"` with a full `results[]` array
- **THEN** the frontend SHALL render all remaining results using the same chat message format as existing UI
- **THEN** each entry in `results[]` SHALL appear with its own avatar based on `backend` name
- **THEN** entries with `backend: "api_docs"` SHALL use the API Docs-specific rendering (confidence badges, reasoning expander, relevant functions/types)
- **THEN** `st.session_state.active_task_id` SHALL be cleared
- **THEN** `st.session_state.query_polling_done` SHALL be set to `True`
- **THEN** `st.session_state._cached_doc_list` and `_cached_doc_statuses` SHALL be cleared
- **THEN** `st.rerun(scope="fragment")` SHALL be called to refresh the view

#### Scenario: Rapid resubmit prevented
- **WHEN** `st.session_state.active_task_id` is set
- **THEN** the chat input SHALL be disabled
- **THEN** the "Clear Chat" button SHALL be disabled or guarded to prevent mid-query message wipe
- **THEN** sidebar parameter widgets SHALL be disabled (temperature, top_k, etc.) to avoid confusion about which params were used
- **THEN** if the user somehow triggers another submit, the previous task SHALL be ignored
- **WHEN** `st.session_state.active_task_id` is set AND the user refreshes the page
- **THEN** `active_task_id` SHALL be cleared (Streamlit session state resets on refresh) — this is acceptable behavior

#### Scenario: Error shown on failure
- **WHEN** status returns `"error"`
- **THEN** the frontend SHALL display the error message using `st.error()`
- **THEN** any completed results in `results[]` SHALL be rendered alongside the error
- **THEN** `st.session_state.active_task_id` SHALL be cleared
- **THEN** `st.session_state.query_polling_done` SHALL be set to `True`
- **THEN** the chat input SHALL be re-enabled
- **THEN** the user SHALL be able to retry

#### Scenario: Task not found (server restart)
- **WHEN** status returns HTTP 404
- **THEN** the frontend SHALL display a message: "Query session expired — please retry"
- **THEN** `st.session_state.active_task_id` SHALL be cleared
- **THEN** `st.session_state.query_polling_done` SHALL be set to `True`
- **THEN** the chat input SHALL be re-enabled

#### Scenario: Network error during polling
- **WHEN** a network error occurs (ConnectionError, Timeout, HTTP 500, DNS failure)
- **THEN** the frontend SHALL retry the poll up to 3 times with 5-second backoff between retries
- **THEN** if all retries fail, the frontend SHALL display: "Connection lost — please check your connection and retry"
- **THEN** `st.session_state.active_task_id` SHALL NOT be cleared (task continues on server)
- **THEN** a "Retry Now" button SHALL allow the user to manually resume polling
- **THEN** the chat input SHALL remain disabled while `active_task_id` is set

### Requirement: RAG backends SHALL use concurrent retrieval with serialized LLM generation

The background task SHALL dispatch retrieval phases concurrently via `asyncio.gather()`. LLM generation SHALL be serialized through the existing `asyncio.Lock` on `MLXLLM`. Each sub-task SHALL write its result to `TaskRecord.results[]` as it completes, enabling per-backend progress visibility. The API Docs query SHALL run as a separate sequential step after all RAG backends complete.

#### Scenario: Retrieval runs concurrently, LLM serialized
- **WHEN** cosine, langchain, and llamaindex are selected
- **THEN** the task SHALL dispatch all three retrieval phases concurrently via `asyncio.gather()`
- **THEN** each backend's retrieval (vector search / BM25) SHALL run in parallel
- **THEN** LLM generation SHALL be serialized: each sub-task acquires the `asyncio.Lock` and waits if another backend is generating
- **THEN** progress text SHALL update between backends (e.g., "Answer 1 of 3 complete" after each backend's result is stored)
- **THEN** the final `results[]` SHALL contain all backend responses

#### Scenario: API Docs runs after RAG backends
- **WHEN** API Docs query is selected alongside the 3 RAG backends
- **THEN** the task SHALL execute all 3 RAG backends first (concurrently for retrieval, serialized LLM), then the API Docs query
- **THEN** the API Docs query SHALL use the internal `api_docs_query()` function (no separate HTTP call)
- **THEN** progress text SHALL reflect API Docs phase (e.g., "Processing API Documentation...")
- **THEN** the final `results[]` SHALL include an entry with `backend: "api_docs"`

#### Scenario: Individual backend failure
- **WHEN** one backend fails with an error during its retrieval or LLM phase
- **THEN** the failed backend's entry in `results[]` SHALL have `status: "error"` with a descriptive message
- **THEN** other backends SHALL continue executing (a failure in one does NOT cancel others)
- **THEN** the task-level `status` SHALL be `"error"` only after ALL backends have completed (or failed)
- **THEN** the frontend SHALL render completed results alongside error indicators for failed backends

### Requirement: Max tokens SHALL be bounded

The `max_tokens` field SHALL have a maximum value of 1200 and a default of 600 across both frontend and backend.

#### Scenario: Schema validates max_tokens
- **WHEN** a request sends `max_tokens: 1500`
- **THEN** the schema SHALL reject it with a validation error (le=1200)
- **WHEN** a request sends `max_tokens: 600`
- **THEN** the schema SHALL accept it

#### Scenario: Frontend slider matches schema bounds
- **WHEN** a user opens the chat page
- **THEN** the Max Tokens slider SHALL have `min_value=64, max_value=1200, value=600`
- **THEN** the user SHALL NOT be able to set a value above 1200

### Requirement: Saved max_tokens SHALL be safely migrated

Users who previously saved `max_tokens > 1200` in their local params file (`data/chat_params.json`) SHALL NOT receive validation errors on their next query.

#### Scenario: Saved max_tokens above cap is clamped
- **WHEN** a user has `max_tokens: 2000` saved in `chat_params.json`
- **THEN** the frontend SHALL clamp the loaded value to 1200 on load
- **THEN** the slider SHALL display `value=1200`
- **THEN** no validation error SHALL be shown
- **THEN** the user SHALL be able to submit a query without error

#### Scenario: Saved max_tokens within bounds passes through
- **WHEN** a user has `max_tokens: 600` saved in `chat_params.json`
- **THEN** the frontend SHALL load the value as-is
- **THEN** the slider SHALL display `value=600`

### Requirement: Frontend SHALL cache document list during polling

To avoid N+2 redundant HTTP requests per poll cycle, the frontend SHALL cache the document list and per-document processing statuses for the duration of the active query.

#### Scenario: Documents cached on submit
- **WHEN** a user submits a query
- **THEN** the current document list and per-document processing statuses SHALL be stored in `st.session_state._cached_doc_list` and `st.session_state._cached_doc_statuses`
- **THEN** the sidebar SHALL use these cached values during the polling phase instead of making new API calls

#### Scenario: Cache cleared on completion
- **WHEN** a query completes, errors, or the task is not found
- **THEN** `st.session_state._cached_doc_list` and `_cached_doc_statuses` SHALL be cleared
- **THEN** the next full page rerun SHALL fetch fresh document data from the API

#### Scenario: Cache does not affect correctness
- **WHEN** a document is processed while a query is running
- **THEN** the sidebar MAY show stale processing status until the query completes
- **THEN** the user cannot submit a new query during polling, so staleness has no effect on query correctness

### Requirement: Frontend SHALL show loading state on initial submit

The frontend SHALL provide immediate visual feedback between the submit button press and the first poll cycle.

#### Scenario: Loading indicator on submit
- **WHEN** a user clicks the submit button
- **THEN** the frontend SHALL immediately show a "Creating query..." indicator (before the POST request completes)
- **THEN** the chat input SHALL be disabled immediately
- **THEN** after the POST returns a `task_id`, the indicator SHALL transition to the polling progress display
- **THEN** if the POST request fails (network error, 500), the indicator SHALL be replaced with an error message

### Requirement: Frontend SHALL handle st.session_state lifecycle correctly

The polling-related session state keys SHALL be managed to prevent rerun storms and orphaned state.

#### Scenario: query_polling_done guard prevents rerun storm
- **WHEN** the `@st.fragment` polling function runs
- **THEN** the fragment SHALL check `st.session_state.query_polling_done` at the top
- **THEN** if the flag is `True`, the fragment SHALL return immediately without polling
- **THEN** the flag SHALL be set to `False` when a new query is submitted

#### Scenario: models_ready interaction during polling
- **WHEN** `st.session_state.active_task_id` is set AND `models_ready` becomes `False` (e.g., server restart)
- **THEN** the model-warmup block SHALL NOT re-trigger the model download during active query
- **THEN** the frontend SHALL show a warning: "Model loading — your query may be delayed"
- **THEN** the polling SHALL continue (the backend task continues independently)
- **THEN** if the backend task completes during model loading, the result SHALL be rendered when models become ready

### Requirement: Task result SHALL use structured per-backend format

The `TaskRecord` SHALL store results as an array of per-backend entries rather than a single combined dict. This enables progressive rendering and independent error tracking.

#### Scenario: Status response format
- **WHEN** a task is processing
- **THEN** `GET /api/v1/query/status/{id}` SHALL return:
  ```json
  {
    "task_id": "uuid",
    "status": "processing",
    "progress": "Answer 1 of 3 complete",
    "results": [
      {"backend": "cosine", "status": "completed", "answer": "...", "sources": [...], "latency_ms": 1234},
      {"backend": "langchain", "status": "processing"},
      {"backend": "llamaindex", "status": "queued"}
    ]
  }
  ```
- **THEN** each entry in `results[]` SHALL have at minimum: `backend` (string), `status` (one of: queued, processing, completed, error)
- **THEN** entries with `status: "completed"` SHALL include `answer`, `sources[]`, and `latency_ms`
- **THEN** entries with `status: "error"` SHALL include `error` (string)
- **THEN** entries with `backend: "api_docs"` SHALL include `rag_type: "api_docs"` field for rendering dispatch

#### Scenario: Rendering dispatches on backend field
- **WHEN** the frontend renders a completed entry from `results[]`
- **THEN** the avatar and message styling SHALL be determined by the `backend` field
- **THEN** if the entry has `rag_type: "api_docs"`, the API Docs-specific rendering SHALL be used (confidence badges, reasoning expander, relevant functions/types listing)
- **THEN** otherwise, the standard RAG backend rendering SHALL be used

### Requirement: ThreadPoolExecutor SHALL be removed from Chat.py

The `ThreadPoolExecutor(max_workers=3)` and `as_completed()` pattern SHALL be removed from the chat page, replaced by the task creation + fragment-scoped polling pattern.

#### Scenario: No ThreadPoolExecutor in query flow
- **WHEN** a user submits a question
- **THEN** the frontend SHALL NOT create a ThreadPoolExecutor
- **THEN** the frontend SHALL NOT call `as_completed()` or `future.result()`
- **THEN** the frontend SHALL use only the task creation + fragment-scoped polling flow
