## Why

The async task polling pattern (added in `fix-rag-ui-freeze`) introduces unnecessary complexity: 7 session state variables, a 265-line poll loop, and constant `st.rerun()` cycling. Meanwhile, the LLM's `asyncio.Lock` serializes generation anyway, so concurrent dispatch provides no wall-time benefit over sequential calls. A simpler sequential loop gives the same total time (~13s for 3 backends), real `st.spinner()` UX, and dramatically less code.

## What Changes

1. **Remove async task infrastructure (backend)**: Delete `_executor.py`, `task_manager.py`. Remove `POST /query/start` and `GET /query/status/{task_id}` endpoints from `routes.py`. Remove all task manager imports.

2. **Simplify frontend query flow**: Replace the async polling loop in `Chat.py` with a sequential for-loop that calls each selected backend's existing sync endpoint (`POST /query`, `/query/langchain`, `/query/llamaindex`, `/query/api-docs`). Each call gets its own `st.spinner()`. Answers appear immediately as each backend completes.

3. **Clean up `query.py`**: Remove `async_query_start()` and `async_query_poll()`. Keep all existing sync helpers.

4. **Keep all backend performance fixes**: Processor flush granularity, batched cross-encoder verification, LangChain silent fallback fix, DSPy asyncio bridge, aiofiles uploads.

## Capabilities

### New Capabilities
- `sequential-query-flow`: Simple sequential query execution in the frontend — for-loop over selected backends, each calling its sync endpoint with `st.spinner()`, rendering results inline as they arrive. Replaces both the previous ThreadPoolExecutor pattern and the recent async polling pattern.

### Modified Capabilities
- `frontend-loading-indicators`: Loading indicator pattern changes from ThreadPoolExecutor + `as_completed()` placeholders to sequential `st.spinner()` wrapping each sync backend call. The concurrent indicator spec scenarios need updating to reflect the simpler sequential model.

## Impact

| Area | Change |
|------|--------|
| `src/api/routes/query/_executor.py` | **Delete** — entire file |
| `src/domain/services/task_manager.py` | **Delete** — entire file |
| `src/api/routes/query/routes.py` | Remove `/start` and `/status/{task_id}` endpoints, remove `_executor` and `task_manager` imports, remove `BackendResultSchema` / `QueryStartRequest` / `TaskStatusResponse` / `QueryStartResponse` schemas |
| `src/api/schemas/query.py` | Remove `BackendResultSchema`, `QueryStartRequest`, `QueryStartResponse`, `TaskStatusResponse` (or keep if shared) |
| `client/pages/3_💬_Chat.py` | Replace async polling with sequential sync loop. ~350 lines removed, ~100 added |
| `client/utils/query.py` | Remove `async_query_start()`, `async_query_poll()` |
