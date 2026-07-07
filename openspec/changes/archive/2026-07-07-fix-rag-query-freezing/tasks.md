## 1. Backend: Async FAISS Initialization

- [x] 1.1 In `src/domain/services/retrieval_langchain.py`, move `text_embeddings` and `metadatas` list construction outside the `FAISS.from_embeddings()` call (pre-compute before thread dispatch)
- [x] 1.2 Wrap the primary `FAISS.from_embeddings()` call (line 312, with real embeddings) in `await asyncio.to_thread()`
- [x] 1.3 Wrap the fallback `FAISS.from_embeddings()` call (line 322, with zero embeddings) in `await asyncio.to_thread()`
- [x] 1.4 Run unit tests to verify no regressions: `uv run pytest tests/unit/`

## 2. Frontend: Concurrent RAG Dispatch

- [x] 2.1 In `client/pages/3_💬_Chat.py`, refactor the 3 sequential `if "cosine"/"langchain"/"llamaindex" in selected_rags` blocks (lines 516-571) to dispatch all selected RAG queries concurrently using `concurrent.futures.ThreadPoolExecutor` or `asyncio.gather()` with `asyncio.to_thread()` wrappers
- [x] 2.2 Ensure each backend result still renders with its own spinner and avatar in the chat UI, preserving the existing UX
- [x] 2.3 Ensure each result is still appended to `st.session_state.messages` independently

## 3. Slow E2E Tests — 4 Pipelines

- [x] 3.1 Create `tests/integration/test_rag_pipelines_e2e.py` with shared `auth_client` fixture and `upload_and_wait_for_document` helper (following `test_chat_e2e.py` / `test_api_docs_e2e.py` patterns)
- [x] 3.2 Implement `test_cosine_pipeline` — upload `test_pdf.pdf` with `recursive` strategy, query `POST /api/v1/query` with "how to add material?", assert 200 + non-empty answer
- [x] 3.3 Implement `test_langchain_pipeline` — reuse same doc_id from cosine, query `POST /api/v1/query/langchain` with "how to add material?", assert 200 + non-empty answer
- [x] 3.4 Implement `test_llamaindex_pipeline` — reuse same doc_id from cosine, query `POST /api/v1/query/llamaindex` with "how to add material?", assert 200 + non-empty answer
- [x] 3.5 Implement `test_api_docs_pipeline` — upload `test docx.docx` with `api-docs` strategy, query `POST /api/v1/query` with "how to add material?" using the API doc doc_id, assert 200 + non-empty answer
- [x] 3.6 All 4 tests tagged `@pytest.mark.slow` — verify they are excluded from default run (`uv run pytest`) and runnable via `uv run pytest -m slow`

## 4. Verify

- [x] 4.1 Run full test suite excluding slow: `uv run pytest -v -m "not slow"`
- [x] 4.2 Run slow e2e tests: `uv run pytest -v -m slow`
- [x] 4.3 Run linting: `uv run ruff check .`
- [x] 4.4 Run type checking: `uv run mypy src/`
