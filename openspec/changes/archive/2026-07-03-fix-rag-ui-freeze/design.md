## Context

The chat page (`client/pages/3_💬_Chat.py`) currently dispatches RAG queries using `concurrent.futures.ThreadPoolExecutor(max_workers=3)` with `as_completed()` and `future.result(timeout=120)`. This blocks Streamlit's single main thread for the entire duration of all selected RAG backends — typically 30-800+ seconds. During this time, the browser tab is non-interactive: no scrolling, no parameter changes.

A previous change (`fix-rag-query-freezing`) introduced this ThreadPoolExecutor pattern to make the 3 backend queries concurrent, but it did not solve the fundamental problem: **the main thread still blocks**.

Additionally, the API Docs query path (Chat.py lines 584-616) runs synchronously *after* the ThreadPoolExecutor block via `api_docs_query()`, adding another ~180s of blocking. Both paths must be covered.

**Critical Streamlit constraint**: `st.rerun()` re-executes the **entire script** from top to bottom. There is no mechanism to skip sidebar, document fetching, or message rendering on a "poll-only" rerun. Each poll cycle re-runs all page logic — including document list fetches (N+1 HTTP calls), chat message rendering, sidebar widget creation, and JS injection. The initial design's assumption that "sidebar/document logic runs once per rerun" is incorrect. A `st.fragment`-based approach (Streamlit 1.33+) is required to scope reruns to only the polling component, avoiding re-execution of the full page on every 2s poll cycle.

The query flow involves:
1. Retrieval (vector/BM25 search) — fast (<1s)
2. Prompt building — fast (<10ms)
3. LLM generation — 18-30s per backend at 600 tokens (30-50ms/token)
4. Cross-encoder verification — moderate (2-5s)
5. Response cleaning — fast

The 3 backends (cosine, langchain, llamaindex) share the same `MLXLLM` singleton guarded by `asyncio.Lock`. With sequential dispatch, total wall time = sum of each backend's generation (3 × ~260s = ~800s for long responses).

Additionally, the frontend `max_tokens` slider defaults to **2048** while the backend schema defaults to **600** — causing 3.3x longer generation than intended.

## Goals / Non-Goals

**Goals:**
- UI MUST remain fully responsive during query execution (scroll, navigate, adjust params)
- Concurrent dispatch for retrieval phases (non-GPU work runs in parallel); only LLM generation is serialized by `asyncio.Lock`
- LLM `asyncio.Lock` stays unchanged (GPU memory safety)
- Max tokens bounded: schema cap 1200, frontend default 600
- Existing `POST /api/v1/query` and streaming endpoints remain functional
- Partial results SHALL be visible as each backend completes (no all-or-nothing wait)

**Non-Goals:**
- True streaming (SSE with progressive token rendering) — deferred to future phase
- Parallel LLM inference — deferred (GPU memory concern)
- Faster LLM generation via model swap — independent decision
- Cross-session task persistence — tasks are in-memory only
## Decisions

### Decision 1: Background task queue over SSE

**Chosen: Task queue (polling)**

The alternative was fixing the existing SSE streaming endpoint. SSE was rejected because:
- For 800s queries, the HTTP connection stays open — proxies/load balancers have tight timeouts (Cloudflare 100s, nginx 60s, our own frontend 160s)
- The answer needs post-processing (verification step), so streamed tokens differ from final rendered answer
- SSE doesn't solve the "should wait" requirement — a dropped connection means lost results

Task queue with polling keeps HTTP requests short (instant status checks) and handles any duration naturally.

### Decision 2: In-memory TaskManager (not DB-backed)

Tasks live in a `dict[str, TaskRecord]` in process memory. On server restart, all tasks are lost. This is acceptable because:
- RAG queries are ephemeral — a lost query is retried by the user
- DB persistence would add complexity (session management in background tasks, cleanup queries)
- The pattern matches the existing model-warmup polling (Chat.py lines 126-190) which also uses in-memory state

**Risk**: Server restart mid-query loses that query. Mitigation: the frontend's next poll gets 404 and shows "Session expired, please retry."

### Decision 3: Concurrent retrieval dispatch, serialized LLM generation

**Chosen: `asyncio.gather()` for retrieval + sequential LLM**

The background task launches 3 concurrent sub-tasks — one per selected RAG backend. Each sub-task performs its own retrieval (vector search / BM25 — CPU-bound, no lock needed) in parallel via `asyncio.gather()`. LLM generation is then sequenced: each sub-task acquires the `asyncio.Lock` on `MLXLLM` one at a time.

```
         ┌── cosine retrieval ──→ await LLM lock → LLM gen → store ─┐
gather() ── langchain retrieval → await LLM lock → LLM gen → store  ──→ mark completed
         └── llamaindex retrieval → await LLM lock → LLM gen → store ─┘
                                            └── [api-docs → store] ──┘
```

Retrieval parallelism reduces wall time: 3 backends × 1s retrieval = 1s instead of 3s. LLM generation still serializes naturally via `asyncio.Lock`, keeping GPU memory at ~3GB peak.

As each sub-task completes, its result is written to `TaskRecord.results[]` so the frontend can poll partial progress.

API Docs query runs after all RAG backends, as a 4th sequential step (no retrieval, just LLM + cross-encoder).

### Decision 4: Lightweight auth for status polling

Status polling uses `decode_access_token()` (JWT decode only, no DB lookup) instead of the full `get_current_user()` dependency. This avoids DB queries on every poll (every 2s per user) and allows the token to be valid for the full query duration without hitting DB. User ownership is enforced by comparing `task.user_id` against `token.sub`.

### Decision 5: Max tokens in the 600-1200 range

The frontend slider was defaulting to 2048 (range 64-4096), which overrode the backend default of 600. The schema cap of 2000 meant users could request up to 2000 tokens, taking 60-100s per generation. Changed to:
- Schema: `ge=50, le=1200` (was `le=2000`)
- Frontend default: **600** (was 2048)
- Frontend max: **1200** (was 4096)

This caps worst-case generation at ~36-60s per backend.

### Decision 6: `st.fragment`-based polling over full-rerun polling

**Chosen: `st.fragment` with `st.rerun(scope="fragment")`**

A `@st.fragment` decorator wraps the polling loop so that `st.rerun(scope="fragment")` only re-runs the fragment, not the entire page. This avoids re-executing sidebar logic, document fetching, chat message rendering, and JS injection on every 2s poll cycle.

```python
@st.fragment
def poll_task_status():
    if st.session_state.get("active_task_id"):
        status = async_query_poll(st.session_state.active_task_id)
        if status["status"] == "processing":
            st.markdown(f"**{status['progress']}**")
            time.sleep(2)
            st.rerun(scope="fragment")
        elif status["status"] == "completed":
            render_result(status["result"])
            del st.session_state.active_task_id
            st.rerun(scope="fragment")
```

The model-warmup pattern (top-of-script guard with `st.rerun()`) is rejected for this use case because:
- The polling needs to coexist with rendered chat messages and UI state below it
- A top-of-script guard would prevent the chat history from rendering during polling
- `@st.fragment` scopes the rerun to only the polling component, leaving the rest of the page interactive

**Requirement**: Streamlit >= 1.33. The project already meets this (verify in `pyproject.toml`).

### Decision 7: Structured partial results in TaskRecord

The status endpoint returns `results` as an array rather than a single combined dict. Each entry is a per-backend result:

```json
{
  "status": "processing",
  "progress": "Answer 1 of 3 complete",
  "results": [
    {"backend": "cosine", "status": "completed", "answer": "...", "sources": [...]},
    {"backend": "langchain", "status": "processing"},
    {"backend": "llamaindex", "status": "queued"}
  ]
}
```

This allows the frontend to render completed backends immediately while others are still running. The rendering code iterates `results[]` and renders each entry with the correct avatar based on `backend` name — the same pattern already used for per-backend chat messages.

### Decision 8: Session-level document list caching during polling

To avoid N+2 HTTP requests on every poll cycle, the document list and per-document processing statuses are cached in `st.session_state` for the duration of the active query:

```python
# On submit: cache current state
st.session_state._cached_doc_list = get_document_list()
st.session_state._cached_doc_statuses = get_doc_statuses()

# On rerun during polling: use cached values
docs = st.session_state.get("_cached_doc_list") or get_document_list()
```

Cache is cleared when `active_task_id` is removed (completed/error/404). The document list in the sidebar may be stale during polling, but the user cannot submit a new query while polling is active, so staleness has no effect on correctness.

### Decision 9: Over-fetch guard and rerun storm prevention

A `st.session_state.query_polling_done` flag prevents the polling fragment from re-entering after a result has been rendered:

```python
# Top of fragment
if st.session_state.get("query_polling_done"):
    return
# ... polling logic ...
# On completion
st.session_state.query_polling_done = True
```

This flag is reset to `False` when a new query is submitted (in the `async_query_start()` flow), ensuring the polling path is active for the next query.

```
┌─────────────────────────────────────────────────────────────────┐
│                      TaskManager                                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  _tasks: dict[str, TaskRecord]                           │   │
│  │                                                          │   │
│  │  TaskRecord {                                            │   │
│  │    task_id: str                                          │   │
│  │    user_id: str                                          │   │
│  │    status: queued|processing|completed|error                │   │
│  │    progress: str  ("Answer 1 of 3 complete...")          │   │
│  │    results: [                                            │   │
│  │      {"backend": "cosine", "status": "completed", ...},  │   │
│  │      {"backend": "langchain", "status": "processing"},   │   │
│  │    ]                                                     │   │
│  │    error: str | None                                     │   │
│  │    created_at: datetime                                  │   │
│  │    _task: asyncio.Task (internal, not serialized)        │   │
│  │  }                                                       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Methods: create(), get(), cleanup() │
└─────────────────────────────────────────────────────────────────┘

New API endpoints:
  POST /api/v1/query/start         →  { task_id }
  GET  /api/v1/query/status/{id}   →  { status, progress, results[], error? }

Frontend flow:
  Submit → POST /start → cache doc list → store task_id → st.rerun()
         → on rerun: @st.fragment poll_task_status() runs (scoped rerun)
         → fragment: poll GET /status, update progress text, time.sleep(2)
         → fragment re-runs every 2s until status is "completed" | "error"
         → on "completed": render results[], clear session state, st.rerun(scope="fragment")
         → on "error": show error, clear session state

  The @st.fragment decorator ensures only the polling component re-runs on each
  2s poll cycle. The rest of the page (sidebar, chat history, document list) is
  NOT re-executed during polling. Full page reruns only happen on:
  1. Initial submit (to enter fragment)
  2. Final result render (to show completed chat message)

Backend task execution:
  asyncio.gather(
    _execute_backend("cosine", ...),      # retrieval + await LLM lock
    _execute_backend("langchain", ...),   # retrieval + await LLM lock
    _execute_backend("llamaindex", ...),  # retrieval + await LLM lock
  )
  Each sub-task writes its result to TaskRecord.results[] on completion.
  If API Docs is selected, runs sequentially after all gather() complete.
```

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Server restart kills running tasks | Lost query result | Frontend shows "Session expired, retry" on 404 |
| Token expires during long query | 401 on status polls | Use lightweight decode-only auth; 30min expiry covers most queries; allow re-auth preserving `active_task_id` |
| Rapid double-click submits | Two tasks for same question | Frontend checks `active_task_id` before creating new task; disables chat input while active |
| TaskManager memory leak | Unbounded dict growth | Periodic cleanup (every 60s, remove tasks older than 15min); cap at 1000 entries |
| Race on TaskManager dict | Corrupted task state | `asyncio.Lock` for all TaskManager operations |
| N+2 request amplification per poll | 6 HTTP calls per poll cycle = 240+ calls over 80s | Cache document list and statuses in `st.session_state` during polling (Decision 8) |
| Rerun storm | Cascading reruns if `active_task_id` not cleared | `query_polling_done` guard flag (Decision 9) |
| User navigates away mid-poll | Task completes while user on another page | Task persists in TaskManager; user sees result when returning to Chat page (if within 15min TTL) |
| Network error during polling | Poll raises ConnectionError / Timeout | Frontend retries up to 3 times with 5s backoff before showing error |
| Partial backend failure loses all results | Backend 3/3 fails → all results lost | Partial results array preserves completed backends; each entry has independent status |
| Fragment unsupported Streamlit version | `st.fragment` not available | Verify Streamlit >= 1.33 in pyproject.toml; fall back to full-rerun polling if older |
