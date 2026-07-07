## Context

The current frontend (`fix-ui-freeze` branch) uses an async task polling pattern:
- `POST /query/start` creates a background task with `TaskManager`
- `GET /query/status/{task_id}` returns progressive per-backend results
- `poll_query_task()` in Chat.py loops every 1s via `st.rerun()`

Before that (`dev` branch), the frontend used `ThreadPoolExecutor` with `as_completed()` — concurrent dispatch of all 3 backends.

Both patterns exist because the UX requirement was "don't freeze the UI." However, the `MLXLLM._generate_lock` (from `fix-gpu-contention`) serializes all LLM generation calls anyway, so neither concurrent pattern actually saves wall time over sequential dispatch. Total time is ~13s for 3 backends regardless of concurrency.

The backend already has working sync endpoints (`POST /query`, `/query/langchain`, `/query/llamaindex`, `/query/api-docs`). The async task infrastructure (`_executor.py`, `task_manager.py`, `/query/start`, `/query/status`) and all frontend polling code can be removed.

All backend performance fixes from `fix-rag-ui-freeze` (processor flush granularity, batched cross-encoder, LangChain fallback, DSPy asyncio bridge, aiofiles) are kept — only the dispatch pattern changes.

## Goals / Non-Goals

**Goals:**
- Replace async polling with sequential sync calls in the frontend
- Delete the backend task manager infrastructure (2 files, 2 endpoints)
- Remove all async polling state and logic from Chat.py
- Keep all backend performance fixes intact
- Maintain responsive UX via `st.spinner()` per backend call

**Non-Goals:**
- No changes to backend sync endpoints or their behavior
- No changes to model loading, LLM singleton, or GPU contention lock
- No changes to the API docs query flow (uses its own endpoint)
- No changes to document processing, upload, or authentication

## Decisions

### Decision 1: Sequential sync over concurrent dispatch
**Choice**: Simple `for` loop calling each backend's sync endpoint sequentially.
**Rationale**: The LLM `asyncio.Lock` serializes all generation calls. Running backends concurrently (via ThreadPoolExecutor or async tasks) provides ~0 wall-time benefit since retrieval is fast (<0.4s) and generation dominates (~4-5s per backend). Sequential dispatch gives same total time with dramatically less code.
**Alternatives considered**:
- *ThreadPoolExecutor + as_completed()* — previous `dev` pattern. Still blocks UI, adds threading complexity, no wall-time benefit.
- *Async task polling* — current `fix-ui-freeze` pattern. 265 lines of polling logic, 7 state variables, constant rerun cycling, no wall-time benefit.

### Decision 2: Keep sync endpoints, remove async task endpoints
**Choice**: Delete `_executor.py` and `task_manager.py`. Remove `/query/start` and `/query/status/{task_id}`. Keep all existing `/query`, `/query/langchain`, `/query/llamaindex`, `/query/api-docs` endpoints.
**Rationale**: The sync endpoints are fully functional, well-tested, and called directly by the sequential frontend. The async endpoints and their infrastructure are only used by the polling frontend — removing both leaves no dead code.
**Risk**: None. The sync endpoints are the original, stable API surface. The async endpoints were additive and the frontend is the only client.

### Decision 3: `st.spinner()` for per-backend feedback
**Choice**: Each backend call gets its own `with st.spinner(f"Querying {backend}..."):` block.
**Rationale**: `st.spinner()` is Streamlit's native progress indicator — it shows a real animated spinner, doesn't block the page from rendering previous results, and auto-clears when the block exits. No placeholder management needed.
**Alternatives considered**:
- *st.progress() + st.empty() placeholders* — previous frontend-loading-indicators approach. More complex, no UX benefit over spinner for sequential calls.
- *st.write("thinking...")* — less visible, no animation.

### Decision 4: Inline rendering, no rerun loop
**Choice**: After each backend call completes, render its answer directly with `st.chat_message()` + `st.markdown()` + source expanders.
**Rationale**: Sequential dispatch means results are known when the function returns — no need to stage them in session state and rerun. The only session state needed is the message history for chat persistence across questions (which already exists).
**Risk**: If a backend errors midway, already-rendered answers from previous backends stay visible. This is correct behavior — partial results are better than all-or-nothing.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| [Backend timeout] One backend hangs for 160s | Subsequent backends (and user) wait | All sync endpoints have 160s timeouts. A future improvement could add per-backend asyncio timeouts with cancellation, but this matches current behavior. |
| [Total time regresses] Without any parallelism, 4 backends could take 4× avg LLM time (~20s) | User waits longer | The LLM lock already serializes generation — there is no parallelism to lose. Wall time is identical to concurrent approaches. |
| [Error in one backend blocks others] If cosine errors, langchain/llamaindex never run | User gets fewer answers than expected | The for-loop catches exceptions per backend via the API response (not raised). An error in backend A logs and shows the error, then backend B runs normally. |

## Open Questions

None — the design is straightforward. Implementation details (exact line-level changes) are captured in tasks.md.
