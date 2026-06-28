## 1. Backend: Async FAISS Initialization

- [ ] 1.1 In `src/domain/services/retrieval_langchain.py`, move `text_embeddings` and `metadatas` list construction outside the `FAISS.from_embeddings()` call (pre-compute before thread dispatch)
- [ ] 1.2 Wrap the primary `FAISS.from_embeddings()` call (line 312, with real embeddings) in `await asyncio.to_thread()`
- [ ] 1.3 Wrap the fallback `FAISS.from_embeddings()` call (line 322, with zero embeddings) in `await asyncio.to_thread()`
- [ ] 1.4 Run unit tests to verify no regressions: `uv run pytest tests/unit/`

## 2. Frontend: Concurrent RAG Dispatch

- [ ] 2.1 In `client/pages/3_💬_Chat.py`, refactor the 3 sequential `if "cosine"/"langchain"/"llamaindex" in selected_rags` blocks (lines 516-571) to dispatch all selected RAG queries concurrently using `concurrent.futures.ThreadPoolExecutor` or `asyncio.gather()` with `asyncio.to_thread()` wrappers
- [ ] 2.2 Ensure each backend result still renders with its own spinner and avatar in the chat UI, preserving the existing UX
- [ ] 2.3 Ensure each result is still appended to `st.session_state.messages` independently

## 3. Verify

- [ ] 3.1 Run full test suite: `uv run pytest tests/ -v`
- [ ] 3.2 Run linting: `uv run ruff check .`
- [ ] 3.3 Run type checking: `uv run mypy src/`
