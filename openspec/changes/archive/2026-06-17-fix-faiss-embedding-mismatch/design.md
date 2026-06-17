## Context

The RAG pipeline supports three query backends: cosine similarity, LangChain (BM25+FAISS hybrid), and LlamaIndex (RRF fusion). All three share the same chunks stored in SQLite, with embeddings computed by the project's `SentenceTransformerEmbedder` during document processing.

The cosine path works correctly — it uses `SentenceTransformerEmbedder` for both indexing and querying, retrieves relevant chunks, and produces accurate answers. The LangChain path is broken in two ways:

1. **Embedding code path mismatch**: LangChain's `FAISS.from_embeddings()` is initialized with pre-computed vectors (correct), but at query time it uses a `HuggingFaceEmbeddings` wrapper that creates a **separate model instance**. Even with the same model name, this introduces subtle differences in:
   - Normalization behavior (`HuggingFaceEmbeddings` always normalizes via `encode_kwargs={"normalize_embeddings": True}`, while the project embedder normalizes conditionally based on `settings.embedding_normalization_enabled`)
   - Tokenizer configuration and model initialization (separate `sentence_transformers` vs `langchain_huggingface` code paths)

2. **FAISS similarity scores discarded**: The `retrieve()` method uses `as_retriever().ainvoke()` which returns documents without scores, then assigns `1/(rank+1)` as a proxy score. This discards all semantic similarity signal and makes every result equally spaced by rank.

The cross-encoder reranker and threshold filtering then operate on these rank-based scores or cross-encoder scores, but without proper normalization the `min_relevance_score` filter can silently drop all results.

## Goals / Non-Goals

**Goals:**
- LangChain hybrid retriever returns the same relevant chunks as the cosine path for the same query
- FAISS query embedding uses the project's `SentenceTransformerEmbedder` (same code path as stored vectors)
- FAISS retrieval preserves actual similarity scores instead of rank-based proxies
- Cross-encoder reranker scores are min-max normalized before threshold filtering
- All existing tests pass; no regressions in the cosine or LlamaIndex paths

**Non-Goals:**
- Changing the LlamaIndex retriever (it already uses `SentenceTransformerEmbedder` correctly)
- Changing the document processing pipeline (embeddings storage format)
- Adding new dependencies or external services
- Performance optimization beyond the fix (e.g., caching query embeddings)
- Modifying the cosine path or the API layer

## Decisions

### Decision 1: Embedding Adapter Instead of Replacing LangChain's FAISS

**Option A (chosen)**: Create a thin `ProjectEmbeddingFunction` adapter that delegates `embed_query()` to the project's `SentenceTransformerEmbedder` via `get_embedder()`. Pass this adapter as the `embedding` parameter to `FAISS.from_embeddings()`.

**Option B**: Replace `FAISS.from_embeddings()` with direct FAISS index operations (bypass LangChain's FAISS class entirely).

**Why A**: LangChain's `FAISS` class is still useful for its integration points (e.g., `as_retriever()`, `similarity_search_with_relevance_scores()`). The only defective part is the embedding function used for queries. By swapping just that, we keep the integration surface and minimize changes. Option B would require reimplementing FAISS search, serialization, and retriever wrapping — unnecessary complexity.

**Adapter design:**
```python
class _ProjectEmbeddingFunction:
    """FAISS-compatible embedding function using the project's SentenceTransformerEmbedder."""
    
    def __init__(self):
        self._lock = asyncio.Lock()
        self._embedder = None
    
    async def _get_embedder(self):
        if self._embedder is None:
            from .embedding import get_embedder, normalize_embedding
            self._embedder = await get_embedder()
        return self._embedder
    
    async def embed_query(self, text: str) -> list[float]:
        embedder = await self._get_embedder()
        emb = await embedder.embed_text(text)
        from .embedding import normalize_embedding
        return normalize_embedding(emb)
    
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Use pre-computed embeddings from DB")
```

Note: `embed_documents()` raises `NotImplementedError` because `FAISS.from_embeddings()` passes pre-computed embeddings — the function is only called for query encoding at search time. If FAISS ever calls `embed_documents()` during initialization, we handle it explicitly.

### Decision 2: Use `similarity_search_with_relevance_scores()` Instead of `as_retriever().ainvoke()`

**Why**: LangChain's `VectorStore.as_retriever().ainvoke()` strips similarity scores. The `similarity_search_with_relevance_scores()` method returns `(Document, float)` tuples with actual FAISS scores. Using these scores directly in the ensemble (alongside BM25 scores) produces meaningful combined scores instead of `0.5 * 1/(rank_bm25+1) + 0.5 * 1/(rank_faiss+1)`.

**Score normalization**: FAISS similarity scores may need normalization depending on the index type. `IndexFlatIP` (inner product) returns raw dot products, which depend on embedding magnitudes. Since we normalize embeddings to unit vectors, dot product = cosine similarity ∈ [-1, 1]. The adapter normalizes query embeddings to match the stored normalized vectors, so scores are consistent.

### Decision 3: Min-Max Normalize Cross-Encoder Scores Before Threshold

**Current (broken)**: Cross-encoder returns raw scores (range depends on model — could be logits or probabilities). These are compared directly against `min_relevance_score=0.15`. If scores are logits in range [-5, 5], no result passes the threshold.

**Fix**: After cross-encoder reranking in `retrieval_langchain.py::retrieve()`, apply the same `normalize_scores()` function used by the cosine path. The LlamaIndex retriever already does this (lines 264-270 in `retrieval_llamaindex.py`).

### Decision 4: No Changes to BM25 Scoring

BM25 scoring in `CustomEnsembleRetriever._aget_relevant_documents()` uses rank-based `1/(rank+1)` for BM25 results. This is acceptable for BM25 (which returns relevance scores but rank-based fusion with FAISS is the hybrid pattern). The key fix is making FAISS contribute meaningful scores so the combined signal is accurate.

## Risks / Trade-offs

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `FAISS.from_embeddings()` calls `embed_documents()` during init | Low | Raise `NotImplementedError` with clear message; fall back to BM25-only if needed |
| Async embedding adds latency to first query | Medium | Already lazy-loaded; subsequent queries use cached model instance |
| FAISS score range varies with index type | Low | Min-max normalize scores before combining with BM25 (already done in cosine path) |
| Behavior change breaks existing expectations | Low | Only the LangChain path changes; it was producing wrong results before |
