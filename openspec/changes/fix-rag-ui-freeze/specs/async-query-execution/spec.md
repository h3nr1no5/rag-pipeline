# Async Query Execution

## Purpose

Enable long-running RAG queries to execute as background tasks, keeping the Streamlit UI fully responsive via polling. Provide task lifecycle management: create, poll status, and cancel.

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

#### Scenario: Task cancelled
- **WHEN** a task was cancelled by the user
- **THEN** the response SHALL contain `{"status": "cancelled", "progress": "Query cancelled by user"}`

#### Scenario: Task ownership enforced
- **WHEN** User A requests the status of User B's task
- **THEN** the endpoint SHALL respond with HTTP 403
- **THEN** the task data SHALL NOT be exposed

#### Scenario: Lightweight auth for polling
- **WHEN** the status endpoint is called
- **THEN** the endpoint SHALL validate the JWT token via `decode_access_token()` (no DB lookup)
- **THEN** the endpoint SHALL compare `task.user_id` against `token.sub`
- **THEN** the endpoint SHALL NOT execute the full `get_current_user()` dependency

### Requirement: Backend SHALL provide task cancellation endpoint

The backend SHALL expose `POST /api/v1/query/cancel/{task_id}` that cancels a running task.

#### Scenario: Cancel running task
- **WHEN** a task exists with `status: "processing"`
- **THEN** the endpoint SHALL call `asyncio.Task.cancel()` on the background task
- **THEN** the response SHALL contain `{"status": "cancelled"}`
- **THEN** subsequent status polls SHALL return `status: "cancelled"`

#### Scenario: Cancel task between backends
- **WHEN** a task is cancelled while no LLM generation is active (between RAG backends)
- **THEN** cancellation SHALL be instant
- **THEN** no further RAG backends SHALL be executed

#### Scenario: Cancel task during LLM generation
- **WHEN** a task is cancelled while LLM generation is running
- **THEN** `CancelledError` SHALL be raised at the next `await` point
- **THEN** the GPU thread SHALL continue to completion but its result SHALL be discarded
- **THEN** the `asyncio.Lock` SHALL be released
- **THEN** subsequent status polls SHALL return `status: "cancelled"`

#### Scenario: Cancel completed task is no-op
- **WHEN** a task has `status: "completed"` and cancel is requested
- **THEN** the endpoint SHALL respond with `{"status": "completed"}`
- **THEN** no action SHALL be taken

#### Scenario: Cancel requires ownership
- **WHEN** User A attempts to cancel User B's task
- **THEN** the endpoint SHALL respond with HTTP 403

### Requirement: TaskManager SHALL cancel all tasks on shutdown

The TaskManager SHALL provide a `cancel_all()` method that signals all active tasks to stop, preventing orphan GPU tasks from holding the `_generate_lock` after server restart.

#### Scenario: Shutdown cancels active tasks
- **WHEN** the server is shutting down (FastAPI lifespan shutdown event)
- **THEN** the lifespan SHALL call `task_manager.cancel_all()`
- **THEN** each active task SHALL receive `asyncio.Task.cancel()`
- **THEN** tasks SHALL transition to `status: "cancelled"`
- **THEN** the shutdown SHALL NOT wait for cancelled tasks to complete

#### Scenario: Server restart mid-query
- **WHEN** a user's query task is running and the server restarts
- **THEN** the shutdown cancels the task
- **THEN** after restart, the task record is gone (in-memory)
- **THEN** the frontend's next status poll SHALL receive HTTP 404
- **THEN** the frontend SHALL display "Query session expired — please retry"

### Requirement: TaskManager SHALL auto-cleanup old tasks

The TaskManager SHALL periodically remove tasks that are no longer needed to prevent memory leaks.

#### Scenario: Periodic cleanup removes expired tasks
- **WHEN** a task has been completed, cancelled, or errored for more than 15 minutes
- **THEN** the cleanup routine SHALL remove it from the in-memory dict
- **THEN** subsequent status polls SHALL return HTTP 404

#### Scenario: Cleanup cap prevents unbounded growth
- **WHEN** the TaskManager dict exceeds 1000 entries
- **THEN** the oldest tasks SHALL be evicted first regardless of age
- **THEN** evicted tasks SHALL return HTTP 404 on status poll

### Requirement: Frontend SHALL use task polling instead of blocking HTTP

The chat page SHALL replace the existing `ThreadPoolExecutor` + `as_completed()` pattern with task creation + polling. The frontend SHALL remain fully interactive between reruns.

#### Scenario: Submit creates task and begins polling
- **WHEN** a user submits a question
- **THEN** the frontend SHALL call `POST /api/v1/query/start` with the query parameters
- **THEN** the returned `task_id` SHALL be stored in `st.session_state.active_task_id`
- **THEN** `st.rerun()` SHALL be called immediately
- **THEN** on rerun, the frontend SHALL check for `active_task_id` and enter a polling loop
- **THEN** the polling loop SHALL use `time.sleep(2)` between status checks (following the model-warmup pattern at Chat.py:126-190)
- **THEN** the polling loop SHALL NOT call `st.rerun()` on each poll — only sidebar/document logic SHALL execute once per rerun
- **THEN** while `status: "processing"`, the frontend SHALL show a spinner with progress text
- **THEN** the loop SHALL continue until status is `"completed"`, `"error"`, or `"cancelled"`
- **THEN** after the loop exits, `st.rerun()` SHALL be called to refresh the message list with the result

#### Scenario: Result rendered on completion
- **WHEN** status returns `"completed"` with a result
- **THEN** the frontend SHALL render the result using the same chat message format as the existing UI
- **THEN** each RAG backend result SHALL appear with its own avatar and formatting
- **THEN** `st.session_state.active_task_id` SHALL be cleared

#### Scenario: Cancel button shown during processing
- **WHEN** `st.session_state.active_task_id` is set and status is `"processing"`
- **THEN** a "Cancel" button SHALL be displayed
- **WHEN** the user clicks Cancel
- **THEN** `POST /api/v1/query/cancel/{task_id}` SHALL be called
- **THEN** the UI SHALL show "Cancelling..." until status confirms cancellation

#### Scenario: Rapid resubmit prevented
- **WHEN** `st.session_state.active_task_id` is set
- **THEN** the chat input SHALL be disabled
- **THEN** if the user somehow triggers another submit, the previous task SHALL be cancelled first

#### Scenario: Error shown on failure
- **WHEN** status returns `"error"`
- **THEN** the frontend SHALL display the error message using `st.error()`
- **THEN** `st.session_state.active_task_id` SHALL be cleared
- **THEN** the chat input SHALL be re-enabled
- **THEN** the user SHALL be able to retry

#### Scenario: Task not found (server restart)
- **WHEN** status returns HTTP 404
- **THEN** the frontend SHALL display a message: "Query session expired — please retry"
- **THEN** `st.session_state.active_task_id` SHALL be cleared
- **THEN** the chat input SHALL be re-enabled

#### Scenario: UI stays responsive during polling
- **WHEN** the frontend is in the polling loop
- **THEN** the user SHALL be able to scroll the chat history
- **THEN** the user SHALL be able to click Cancel
- **THEN** the user SHALL be able to navigate to other pages
- **THEN** the browser tab SHALL NOT show "not responding"

### Requirement: RAG backends and API Docs SHALL execute sequentially inside background task

The background task SHALL execute each selected backend one at a time, not in parallel. This includes the API Docs query as a fourth optional step after the 3 RAG backends. This keeps GPU memory usage low and respects the existing `asyncio.Lock` on `MLXLLM`.

#### Scenario: Backends run in order
- **WHEN** cosine, langchain, and llamaindex are selected
- **THEN** the task SHALL execute cosine first, then langchain, then llamaindex
- **THEN** each backend SHALL wait for the previous one to complete before starting
- **THEN** progress text SHALL update between backends (e.g., "Answer 1 of 3 complete")
- **THEN** the final result SHALL contain all three backend responses

#### Scenario: API Docs runs after RAG backends
- **WHEN** API Docs query is selected alongside the 3 RAG backends
- **THEN** the task SHALL execute all 3 RAG backends first, then the API Docs query
- **THEN** the API Docs query SHALL use the `api_docs_query()` function internally (no separate HTTP call)
- **THEN** progress text SHALL reflect API Docs (e.g., "Processing API Documentation...")
- **THEN** the final result SHALL include API Docs response alongside the RAG backend responses

#### Scenario: Error stops execution
- **WHEN** one backend fails with an error
- **THEN** subsequent backends SHALL NOT be executed
- **THEN** the task SHALL report `status: "error"` with the failed backend's error message
- **THEN** results from completed backends SHALL be available (if any)

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

### Requirement: Cancel semantics SHALL be documented

The cancellation behavior ("cancel stops scheduling, not GPU work") SHALL be made visible to the user so they understand what happens when they cancel.

#### Scenario: Cancel button shows explanatory text
- **WHEN** the Cancel button is clicked
- **THEN** the UI SHALL display "Cancelling — finishing current operation..." (not "Stopped")
- **WHEN** cancellation is confirmed (status returns "cancelled")
- **THEN** the UI SHALL display "Query cancelled. Completed backends are shown above."
- **THEN** any partial results from completed backends SHALL remain visible

### Requirement: ThreadPoolExecutor SHALL be removed from Chat.py

The `ThreadPoolExecutor(max_workers=3)` and `as_completed()` pattern SHALL be removed from the chat page, replaced by the task creation + polling pattern.

#### Scenario: No ThreadPoolExecutor in query flow
- **WHEN** a user submits a question
- **THEN** the frontend SHALL NOT create a ThreadPoolExecutor
- **THEN** the frontend SHALL NOT call `as_completed()` or `future.result()`
- **THEN** the frontend SHALL use only the task creation + polling flow
