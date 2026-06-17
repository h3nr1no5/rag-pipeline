## 1. Core Refactor — Replace Chroma with SQLite

- [ ] 1.1 Rewrite `llama_index_service.py` — Remove all Chroma imports and usage (`chromadb`, `ChromaVectorStore`, `VectorStoreIndex`, `StorageContext`, `LIDocument`). Replace with a `SqliteNodeLoader` that queries `Chunk` rows by `document_id` and returns chunk data ready for constructing `NodeWithScore` objects. The `build_index()` method becomes a no-op (or is removed). The `delete_document()` method becomes a no-op.
- [ ] 1.2 Refactor `retrieval_llamaindex.py` — Replace `VectorStoreIndex.as_retriever()` in `HybridRetriever` with a `_dense_retrieve()` method that embeds the query via `get_embedder()`, normalizes via `normalize_embedding()`, and computes exact dot-product against all chunk embeddings. Update `_ensure_engine()` to load chunks from SQLite directly instead of via `LlamaIndexService.get_index()`. Remove the `aretrieve("")` dump-all-nodes hack; use `WHERE document_id IN (...)` queries instead.
- [ ] 1.3 Remove `_index_chunks_into_chroma()` from `processor.py` — Delete the function definition and both callsites (lines ~333 and ~481). Also remove the `_sanitize_chroma_metadata()` helper.
- [ ] 1.4 Remove Chroma deletion from `documents.py` — Delete the `get_llama_index_service()` / `delete_document()` call block (lines ~305-314).

## 2. Cleanup — Remove Chroma dependencies and artifacts

- [ ] 2.1 Remove `chroma_persist_dir` from `src/core/config.py`
- [ ] 2.2 Remove `chromadb` and `llama-index-vector-stores-chroma` from `pyproject.toml` dependencies list
- [ ] 2.3 Delete `data/chromadb/` directory (no longer needed)
- [ ] 2.4 Run `uv sync` to verify dependency resolution succeeds without chromadb

## 3. Testing — Verify everything still works

- [ ] 3.1 Update `tests/integration/test_score_normalization.py` — Remove comments referencing "Chroma required" for LlamaIndex backend tests (lines ~146, ~196). The LlamaIndex backend no longer requires Chroma, so those tests can run unconditionally.
- [ ] 3.2 Run `uv run pytest -v` and confirm all tests pass (no regressions)
- [ ] 3.3 Manual smoke test: upload a PDF, verify all 3 backends (cosine, LangChain, LlamaIndex) return results for a query
