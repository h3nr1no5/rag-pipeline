## 1. Pipeline Optimization — Reduce Candidate Pool

- [x] 1.1 Reduce `internal_top_k` from 20 to 10 in `retrieval_langchain.py` `retrieve()` method
- [x] 1.2 Verify BM25 and FAISS `k` parameters update accordingly (from 40 to 20 each)

## 2. Pipeline Optimization — Backend Timeout

- [x] 2.1 Add `asyncio.wait_for()` wrapper (160s timeout) around LangChain query execution in `routes.py`
- [x] 2.2 Return HTTP 500 with clear timeout message when exceeded
- [x] 2.3 Cancel the in-flight query task on timeout to free resources

## 3. Frontend Error Key — Query Functions

- [x] 3.1 Add `"error": "transport_error"` to `query_sync()` exception handler (cosine backend)
- [x] 3.2 Add `"error": "transport_error"` to `query_langchain_sync()` exception handler with LangChain-specific timeout message
- [x] 3.3 Add `"error": "transport_error"` to `query_llamaindex_sync()` exception handler
- [x] 3.4 Add `"error": "transport_error"` to `api_docs_query()` exception handler
- [x] 3.5 Add `"error": "http_error"` to non-200 response handlers in all 4 query functions

## 4. Frontend Error Key — Chat Page Rendering

- [x] 4.1 Update Chat page to check `result.get("error")` and render via `st.error()` for transport/HTTP errors
- [x] 4.2 Ensure error messages are not added to chat history as normal assistant messages

## 5. Verify

- [x] 5.1 Run `uv run pytest tests/ -v` to verify no regressions — 545 passed, 82 skipped ✅
- [x] 5.2 Run `uv run ruff check .` and `uv run mypy src/` for lint/typecheck — both clean ✅
- [ ] 5.3 Start backend (no --reload) and run a LangChain query to verify pipeline completes under 180s — optional, requires running server with models
