## 1. Backend — Remove Task Manager Infrastructure

- [ ] 1.1 Delete `src/api/routes/query/_executor.py` (entire file — async RAG dispatch)
- [ ] 1.2 Delete `src/domain/services/task_manager.py` (entire file — TaskManager, TaskRecord, TaskLimitError)
- [ ] 1.3 Remove async task endpoints from `src/api/routes/query/routes.py`: delete `POST /start` and `GET /status/{task_id}` route handlers
- [ ] 1.4 Remove task manager imports from `routes.py`: remove `import` for `task_manager`, `TaskLimitError`, `execute_rag_query`, `QueryStartRequest`, `QueryStartResponse`, `TaskStatusResponse`, `BackendResultSchema`
- [ ] 1.5 Clean up `src/api/schemas/query.py`: remove `BackendResultSchema`, `QueryStartRequest`, `QueryStartResponse`, `TaskStatusResponse` (if not shared elsewhere)

## 2. Frontend — Simplify Chat.py Query Flow

- [ ] 2.1 Replace `async_query_start` + `async_query_poll` imports with direct `requests.post` calls to sync endpoints
- [ ] 2.2 Remove all task-related session state variables: `active_task_id`, `active_query_params`, `task_started`, `query_polling_done`
- [ ] 2.3 Replace the `submit` handler block (lines ~823-863) with a sequential for-loop over selected backends, each wrapped in `st.spinner()`
- [ ] 2.4 Delete the `poll_query_task()` function (lines ~516-781) entirely, including the call at line 866
- [ ] 2.5 Add an inline render helper that takes a backend result and renders it with avatar, label, sources expander, and API docs extras
- [ ] 2.6 Append each answer to `st.session_state.messages` after rendering

## 3. Frontend — Clean Up query.py

- [ ] 3.1 Remove `async_query_start()` function
- [ ] 3.2 Remove `async_query_poll()` function
- [ ] 3.3 Verify all existing sync helper functions (`query_sync`, `query_langchain_sync`, `query_llamaindex_sync`, `api_docs_query`) remain intact

## 4. Verify

- [ ] 4.1 Run `uv run ruff check .` — no lint errors
- [ ] 4.2 Run `uv run mypy src/` — no type errors (or no new ones)
- [ ] 4.3 Run `uv run pytest tests/unit/ -v` — all unit tests pass
- [ ] 4.4 Run `uv run pytest tests/integration/test_query_routes.py -v` — query integration tests pass
- [ ] 4.5 Start backend (`uvicorn src.api.main:app --port 8000`) and verify no import errors on startup
