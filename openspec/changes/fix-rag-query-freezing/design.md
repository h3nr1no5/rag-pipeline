## Context

The RAG pipeline uses an async FastAPI backend with 3 retrieval backends: cosine similarity, LangChain (BM25+FAISS), and LlamaIndex. During queries, the system freezes for 10-30 seconds because synchronous, CPU-bound operations block the asyncio event loop.

Previous fixes addressed BM25 construction and LLM model loading by wrapping them in `asyncio.to_thread()`. However, `FAISS.from_embeddings()` in `LangChainRetriever.initialize()` remains synchronous — it builds a FAISS index from all chunk embeddings directly in the event loop.

Additionally, the Streamlit frontend (`client/pages/3_💬_Chat.py:360-410`) dispatches queries to all 3 RAG backends **sequentially** per chat message. Since all 3 default to enabled, a single slow endpoint triple-walls the user experience.

### Current call path (LangChain query):
1. User sends chat message
2. Frontend sends HTTP POST to `/api/v1/query/langchain`
3. Backend calls `LangChainRetriever.initialize()` (async entry, sync FAISS inside)
4. `FAISS.from_embeddings()` processes all chunk embeddings — **blocks event loop**
5. Ensemble retriever runs BM25 + FAISS search — BM25 is already async via earlier fix
6. LLM generates response — model loading is already async via earlier fix

## Goals / Non-Goals

**Goals:**
- Eliminate all synchronous event-loop blocking from the RAG query request path
- Wrap `FAISS.from_embeddings()` in `asyncio.to_thread()` to match the BM25 and LLM patterns
- Parallelize frontend RAG dispatch so slow backends don't compound user wait time
- All existing tests continue to pass with no behavioral changes

**Non-Goals:**
- Not changing the RAG backend selection logic or query routing
- Not changing the FAISS storage format or location (still `data/vectorstore/`)
- Not introducing background worker queues or persistent job infrastructure
- Not changing the API contract or response format

## Decisions

### Decision 1: Use `asyncio.to_thread()` for FAISS initialization

- **Chosen**: `asyncio.to_thread()` — the same approach already used for BM25 and LLM loading. Runs the synchronous `FAISS.from_embeddings()` in the default thread pool executor without blocking the event loop.
- **Alternatives considered**: 
  - `loop.run_in_executor()` — functionally identical but more verbose. `asyncio.to_thread()` is the Python 3.11+ preferred wrapper.
  - Refactoring FAISS to use its native async API — FAISS has no async API. Would require building a custom async wrapper.
  - Pre-building the FAISS index at ingest time rather than query time — larger refactor, changes initialization lifecycle.
- **Why**: Consistency with existing pattern; minimal code change; proven approach from BM25/LLM fixes.

### Decision 2: Pre-compute list arguments before thread dispatch

- Synchronous `FAISS.from_embeddings()` receives lists of `(content, embedding)` tuples. Building these lists is pure Python (fast, non-blocking), so we pre-compute them before dispatching to the thread.
- Only the `FAISS.from_embeddings()` call itself (the CPU-bound C++/NumPy FAISS index build) goes into the thread pool.

### Decision 3: Parallelize frontend with `asyncio.gather()`

- **Chosen**: Use Python `asyncio.gather()` in the Streamlit backend to send all 3 RAG HTTP requests concurrently, returning once the fastest completes (or all complete).
- **Alternatives considered**:
  - `concurrent.futures.ThreadPoolExecutor` — works but adds complexity. `asyncio.gather()` is the native async approach.
  - JavaScript `Promise.all()` in the frontend — Streamlit runs Python, not JS. Would need significant frontend rework.
- **Why**: Minimal change to the existing code structure; keeps the response model unchanged (returns all 3 results but computes them concurrently).

### Decision 4: No model readiness gate

- The previous `WarmupState` gate was removed in earlier commits. With all async fixes in place (BM25, LLM loading, FAISS), the race condition between warmup and first query is addressed at the source — no gate needed.

## Risks / Trade-offs

- **[Risk] Thread pool contention**: Both BM25 and FAISS now run in the default thread pool. Under heavy load, threads may compete for CPU. **Mitigation**: The default `ThreadPoolExecutor` uses `min(32, os.cpu_count() + 4)` threads — sufficient for a single-user local deployment.
- **[Risk] `FAISS.from_embeddings()` is not trivially thread-safe**: If LangChain's FAISS wrapper has thread-unsafe internals, running it in a thread could cause corruption. **Mitigation**: The call is wrapped in `asyncio.to_thread()` which serializes access to a single call per event-loop iteration. Each `initialize()` call creates a new FAISS instance (no shared state).
- **[Trade-off] Parallel frontend → more simultaneous backend load**: With concurrent dispatch, 3 RAG backends may be queried simultaneously, increasing peak CPU/memory. **Mitigation**: This is better than sequential — peak load is the same duration but total user wait is 3x shorter. Each backend runs on the same machine, so they share the thread pool.
- **[Trade-off] First query latency still includes initialization**: All async fixes move blocking work off the event loop but don't eliminate the initialization work itself. The first query after app start will still trigger BM25 build, FAISS build, and LLM load — but concurrently rather than sequentially blocking.
