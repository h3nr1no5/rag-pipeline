## 1. LangChain BM25 Async Loading

- [ ] 1.1 Make `_ensure_retriever` an `async def` function in `retrieval_langchain.py`
- [ ] 1.2 Wrap `BM25Retriever.from_documents()` in `await asyncio.to_thread()` inside `_ensure_retriever`
- [ ] 1.3 Update all callers of `_ensure_retriever` to `await` it

## 2. LlamaIndex BM25 Async Loading

- [ ] 2.1 Make `_ensure_components` an `async def` function in `retrieval_llamaindex.py`
- [ ] 2.2 Wrap `BM25Okapi(tokenized_docs)` in `await asyncio.to_thread()` inside `_ensure_components`
- [ ] 2.3 Update all callers of `_ensure_components` to `await` it

## 3. Concurrent Model Warmup

- [ ] 3.1 Change `_load_models()` in `main.py` to use `asyncio.gather()` for concurrent model loading
- [ ] 3.2 Verify all model loading functions are idempotent (safe for concurrent calls)

## 4. Verification

- [ ] 4.1 Run unit tests: `uv run pytest -v -m "not slow"`
- [ ] 4.2 Run lint: `uv run ruff check .`
- [ ] 4.3 Run typecheck: `uv run mypy src/`
