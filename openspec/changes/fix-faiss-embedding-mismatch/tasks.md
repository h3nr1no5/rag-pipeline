## 1. Embedding Adapter

- [ ] 1.1 Create `_ProjectEmbeddingFunction` class in `retrieval_langchain.py` that wraps `get_embedder()` and delegates `embed_query()` to the project's `SentenceTransformerEmbedder`
- [ ] 1.2 Ensure `embed_documents()` raises `NotImplementedError` with a clear message (pre-computed embeddings from DB are used instead)

## 2. FAISS Initialization

- [ ] 2.1 Replace `_get_embeddings()` method in `LangChainRetriever` — return a `_ProjectEmbeddingFunction` instance instead of `HuggingFaceEmbeddings`
- [ ] 2.2 Update `FAISS.from_embeddings()` call in `initialize()` to pass the new adapter as the `embedding` parameter
- [ ] 2.3 Remove `_get_embedding_function()` method (no longer needed; scoring uses `similarity_search_with_relevance_scores()` directly)

## 3. FAISS Retrieval Scoring

- [ ] 3.1 In `retrieve()` method, replace `faiss_retriever.ainvoke()` with `self._faiss_vectorstore.asimilarity_search_with_relevance_scores()` to get actual similarity scores
- [ ] 3.2 Update score dictionary to use actual FAISS scores instead of `1/(rank+1)`
- [ ] 3.3 Apply same fix to the deprecated `retrieve_with_scores()` method for consistency

## 4. Cross-Encoder Score Normalization

- [ ] 4.1 After cross-encoder reranking in `retrieve()`, import and apply `normalize_scores()` from `domain/services/embedding.py` before the `min_relevance_score` filter
- [ ] 4.2 Verify normalization happens before threshold and does not affect the sort order (already sorted by cross-encoder scores descending)

## 5. Cleanup

- [ ] 5.1 Remove unused `from langchain_huggingface import HuggingFaceEmbeddings` import (only used by the now-replaced `_get_embeddings()`)
- [ ] 5.2 Run all existing tests to confirm no regressions: `uv run pytest tests/ -v -x`

## 6. Verification Test

- [ ] 6.1 Write a unit test that compares LangChain hybrid retriever results against cosine path results for a known query, verifying at least 3/5 top chunks overlap and the top chunk contains `EWindowState`
- [ ] 6.2 Run test and confirm it passes
