## Why

PC freezes for 10-30 seconds during LangChain and LlamaIndex RAG queries because synchronous CPU-bound operations block the async event loop. The primary remaining bottleneck is `FAISS.from_embeddings()` which processes all chunk embeddings synchronously during every LangChain query initialization. Additionally, the frontend issues 3 sequential HTTP requests per chat message (cosine → langchain → llamaindex), compounding any single-endpoint delay into the total user wait time.

## What Changes

1. **Wrap `FAISS.from_embeddings()` in `asyncio.to_thread()`** in `retrieval_langchain.py` — moves synchronous FAISS index building off the event loop into a thread pool, the same pattern already applied to BM25 and LLM loading.
2. **Parallelize frontend RAG dispatch** in `client/pages/3_💬_Chat.py` — change the 3 sequential HTTP requests to run concurrently via `asyncio.gather()` or `threading.Thread`, so a slow single backend doesn't triple the total wait.
3. **All 3 RAG backends and the warmup path will be fully async-safe** — no synchronous event-loop blocking remains in the request path.

## Capabilities

### New Capabilities
- `async-rag-initialization`: Covers async-safe initialization of all RAG backend components (FAISS index building, BM25 construction, embedding loading) — ensuring zero synchronous event-loop blocking during RAG query processing.

### Modified Capabilities

None — no existing specs are affected. This is an implementation-level performance fix within existing capabilities.

## Impact

- `src/domain/services/retrieval_langchain.py` — `initialize()` method: wrap both `FAISS.from_embeddings()` call sites in `await asyncio.to_thread()` to move synchronous FAISS index building off the event loop.
- `client/pages/3_💬_Chat.py` — RAG dispatch logic around lines 360-410: change from sequential per-backend HTTP requests to concurrent dispatch.
- No new dependencies, no API contract changes, no database schema changes.
