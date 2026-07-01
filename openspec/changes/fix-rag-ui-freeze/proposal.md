## Why

The chat UI freezes completely for 30-800+ seconds while processing a RAG query. The page is non-interactive — user can't scroll, cancel, navigate, or adjust parameters. The existing fix (`fix-rag-query-freezing`) added concurrent `ThreadPoolExecutor` dispatch but still blocks Streamlit's single main thread on `as_completed()` + `future.result(timeout=120)`, leaving the UI frozen.

Additionally, the frontend sends `max_tokens=2048` by default while the backend defaults to `600` — causing 3.3x longer LLM generation than necessary.

## What Changes

1. **Background task queue**: New `POST /query/start`, `GET /query/status/{id}`, `POST /query/cancel/{id}` endpoints. Queries run as background `asyncio.Task`, UI polls for status.
2. **Frontend polling**: Replace the blocking `ThreadPoolExecutor` + `as_completed()` pattern with task creation + `st.rerun()` polling loop. UI stays fully responsive between reruns.
3. **Sequential RAG dispatch inside task**: Each selected RAG backend runs one-at-a-time inside the background task (not parallel). LLM `asyncio.Lock` stays — memory footprint stays low.
4. **Max tokens bounds fix**: Schema max reduced from 2000 to 1200, frontend slider default reduced from 2048 to 600 (matching backend default).
5. **Remove `ThreadPoolExecutor`**: The concurrent dispatch pattern from `fix-rag-query-freezing` is reverted — no longer needed.

## Capabilities

### New Capabilities
- `async-query-execution`: Background task creation for RAG queries, status polling endpoint, cancellation endpoint, and frontend polling loop that keeps the UI responsive

### Modified Capabilities
No existing spec requirements change — the async pattern is additive. The existing `POST /api/v1/query` endpoints remain fully functional for backward compatibility.

## Impact

| Area | Impact |
|------|--------|
| `src/api/routes/query/routes.py` | Add 3 new endpoints (start, status, cancel) |
| `src/domain/services/task_manager.py` | New file — `TaskManager` class + `TaskRecord` |
| `client/pages/3_💬_Chat.py` | Replace lines 534-616 with task creation + polling loop |
| `client/utils/query.py` | Add async query helpers |
| `src/api/schemas/query.py` | Reduce `max_tokens` le from 2000 to 1200 |
| `src/api/main.py` | Wire TaskManager cleanup in lifespan |
| `src/domain/services/llm.py` | No change — `asyncio.Lock` stays |
