## Why

LangChain and LlamaIndex query endpoints return 180s read timeouts while the main cosine path works fine. This is caused by synchronous BM25 index building on first request freezing the event loop, compounded by sequential model warmup that delays model availability.

## What Changes

- Wrap BM25 index building in `asyncio.to_thread()` for both LangChain and LlamaIndex backends
- Make model warmup concurrent via `asyncio.gather()` instead of sequential
- No new endpoints, no API contract changes, no breaking changes

## Capabilities

### New Capabilities
- `async-bm25-loading`: BM25 keyword index built in thread pool to prevent event loop blocking during request handling

### Modified Capabilities
- `model-warmup`: Change sequential model loading (`cross_encoder → llm → embedder`) to concurrent via `asyncio.gather()`

## Impact

- `src/infrastructure/rag/retrieval_langchain.py` — wrap `BM25Retriever.from_documents()` in `asyncio.to_thread()`
- `src/infrastructure/rag/retrieval_llamaindex.py` — wrap `BM25Okapi(tokenized)` in `asyncio.to_thread()`
- `src/api/main.py` — use `asyncio.gather()` for warmup tasks
- Resolves 180s timeout on `/api/v1/query/langchain` and `/api/v1/query/llamaindex`
- No API contract changes
