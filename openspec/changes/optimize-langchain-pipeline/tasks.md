## 1. Pipeline Optimization — Reduce Candidate Pool

- [ ] 1.1 Reduce `internal_top_k` from 20 to 10 in `retrieval_langchain.py` `retrieve()` method
- [ ] 1.2 Verify BM25 and FAISS `k` parameters update accordingly (from 40 to 20 each)

## 2. Pipeline Optimization — Backend Timeout

- [ ] 2.1 Add `asyncio.wait_for()` wrapper (160s timeout) around LangChain query execution in `routes.py`
- [ ] 2.2 Return HTTP 500 with clear timeout message when exceeded
- [ ] 2.3 Cancel the in-flight query task on timeout to free resources

## 3. Frontend Error Key — Query Functions

- [ ] 3.1 Add `"error": "transport_error"` to `query_sync()` exception handler (cosine backend)
- [ ] 3.2 Add `"error": "transport_error"` to `query_langchain_sync()` exception handler with LangChain-specific timeout message
- [ ] 3.3 Add `"error": "transport_error"` to `query_llamaindex_sync()` exception handler
- [ ] 3.4 Add `"error": "transport_error"` to `api_docs_query()` exception handler
- [ ] 3.5 Add `"error": "http_error"` to non-200 response handlers in all 4 query functions

## 4. Frontend Error Key — Chat Page Rendering

- [ ] 4.1 Update Chat page to check `result.get("error")` and render via `st.error()` for transport/HTTP errors
- [ ] 4.2 Ensure error messages are not added to chat history as normal assistant messages

## 5. Verify

- [ ] 5.1 Run `uv run pytest tests/ -v` to verify no regressions
- [ ] 5.2 Run `uv run ruff check .` and `uv run mypy src/` for lint/typecheck
- [ ] 5.3 Start backend (no --reload) and run a LangChain query to verify pipeline completes under 180s
