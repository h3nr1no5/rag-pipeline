## Context

The chat page (`client/pages/3_💬_Chat.py`) currently dispatches RAG queries using `concurrent.futures.ThreadPoolExecutor(max_workers=3)` with `as_completed()` and `future.result(timeout=120)`. This blocks Streamlit's single main thread for the entire duration of all selected RAG backends — typically 30-800+ seconds. During this time, the browser tab is non-interactive: no scrolling, no parameter changes, no cancellation.

A previous change (`fix-rag-query-freezing`) introduced this ThreadPoolExecutor pattern to make the 3 backend queries concurrent, but it did not solve the fundamental problem: **the main thread still blocks**.

Additionally, the API Docs query path (Chat.py lines 584-616) runs synchronously *after* the ThreadPoolExecutor block via `api_docs_query()`, adding another ~180s of blocking. Both paths must be covered.

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
- UI MUST remain fully responsive during query execution (scroll, navigate, cancel, adjust params)
- User MUST be able to cancel a running query
- Sequential RAG dispatch inside background task (1 at a time, low memory)
- LLM `asyncio.Lock` stays unchanged (GPU memory safety)
- Max tokens bounded: schema cap 1200, frontend default 600
- Existing `POST /api/v1/query` and streaming endpoints remain functional

**Non-Goals:**
- True streaming (SSE with progressive token rendering) — deferred to future phase
- Parallel LLM inference — deferred (memory concern)
- Faster LLM generation via model swap — independent decision
- Cancellation during active GPU generation (cancel takes effect between backends or after generation completes)

## Decisions

### Decision 1: Background task queue over SSE

**Chosen: Task queue (polling)**

The alternative was fixing the existing SSE streaming endpoint. SSE was rejected because:
- For 800s queries, the HTTP connection stays open — proxies/load balancers have tight timeouts (Cloudflare 100s, nginx 60s, our own frontend 160s)
- The answer needs post-processing (verification step), so streamed tokens differ from final rendered answer
- SSE doesn't solve the "should wait" requirement — a dropped connection means lost results

Task queue with polling keeps HTTP requests short (instant status checks), handles any duration, and supports cancellation naturally.

### Decision 2: In-memory TaskManager (not DB-backed)

Tasks live in a `dict[str, TaskRecord]` in process memory. On server restart, all tasks are lost. This is acceptable because:
- RAG queries are ephemeral — a lost query is retried by the user
- DB persistence would add complexity (session management in background tasks, cleanup queries)
- The pattern matches the existing model-warmup polling (Chat.py lines 126-190) which also uses in-memory state

**Risk**: Server restart mid-query loses that query. Mitigation: the frontend's next poll gets 404 and shows "Session expired, please retry."

### Decision 3: Sequential dispatch inside background task (incl. API Docs)

Each selected backend runs one-at-a-time. The API Docs query is treated as a fourth optional step:

```
cosine → LLM → store result → langchain → LLM → store result → llamaindex → LLM → store result → [api-docs → store result] → mark completed
```

Not parallel. This keeps GPU memory low (~3GB peak, same as now). The `asyncio.Lock` on `MLXLLM` stays. Cancellation between backends is instant — if cancelled during API Docs, no further steps run.

### Decision 4: Lightweight auth for status polling

Status polling uses `decode_access_token()` (JWT decode only, no DB lookup) instead of the full `get_current_user()` dependency. This avoids DB queries on every poll (every 2s per user) and allows the token to be valid for the full query duration without hitting DB. User ownership is enforced by comparing `task.user_id` against `token.sub`.

### Decision 5: Max tokens in the 600-1200 range

The frontend slider was defaulting to 2048 (range 64-4096), which overrode the backend default of 600. The schema cap of 2000 meant users could request up to 2000 tokens, taking 60-100s per generation. Changed to:
- Schema: `ge=50, le=1200` (was `le=2000`)
- Frontend default: **600** (was 2048)
- Frontend max: **1200** (was 4096)

This caps worst-case generation at ~36-60s per backend.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      TaskManager                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  _tasks: dict[str, TaskRecord]                       │   │
│  │                                                      │   │
│  │  TaskRecord {                                        │   │
│  │    task_id: str                                      │   │
│  │    user_id: str                                      │   │
│  │    status: queued|processing|completed|error|cancelled│   │
│  │    progress: str  ("Answer 1 of 3 complete...")      │   │
│  │    result: dict | None                               │   │
│  │    created_at: datetime                              │   │
│  │    _task: asyncio.Task (internal, not serialized)     │   │
│  │  }                                                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Methods: create(), get(), cancel(), cancel_all(), cleanup() │
└─────────────────────────────────────────────────────────────┘

New API endpoints:
  POST /api/v1/query/start        →  { task_id }
  GET  /api/v1/query/status/{id}   →  { status, progress, result? }
  POST /api/v1/query/cancel/{id}  →  { status }

Frontend flow:
  Submit → POST /start → store task_id → st.rerun()
         → on rerun: start time.sleep() loop (like model-warmup at Chat.py:126-190)
         → each iteration: poll GET /status, update spinner/progress, sleep(2)
         → loop exits when status is "completed", "error", or "cancelled"
         → render result → st.rerun() to refresh message list

  NOTE: The time.sleep() loop runs inside a dedicated code path on each rerun
  cycle (not re-executing sidebar/document logic on every poll). Only the initial
  poll and the final render trigger st.rerun().
```

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Server restart kills running tasks | Lost query result + orphan GPU tasks may hold `_generate_lock` for 300s | Frontend shows "Session expired, retry" on 404; lifespan shutdown calls `cancel_all()` to signal active tasks |
| Token expires during long query | 401 on status polls | Use lightweight decode-only auth; 30min expiry covers most queries |
| Rapid double-click submits | Two tasks for same question | Frontend checks `active_task_id` before creating new task; cancels previous if exists |
| TaskManager memory leak | Unbounded dict growth | Periodic cleanup (every 60s, remove tasks older than 15min); cap at 1000 entries |
| Race on TaskManager dict | Corrupted task state | `asyncio.Lock` for all TaskManager operations |
| Cancel during LLM generation | GPU thread continues | Acceptable — result is discarded, thread frees naturally, user sees "Cancelling..." |
