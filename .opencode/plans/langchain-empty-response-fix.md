# Fix: LangChain returns "I don't have enough information" when docs contain the answer

## Root Cause

`retrieval_langchain.py:291` — `retrieve_with_scores()` calls `self._faiss_vectorstore.as_retriever()` without checking if `_faiss_vectorstore` is `None`. When FAISS initialization fails (embedding model not loaded, dimension mismatch, etc.), `initialize()` catches the exception and sets `_faiss_vectorstore = None` (line 189-190). The `retrieve_with_scores()` method then crashes with `AttributeError`, the broad `except` at line 347 returns `[]`, and the route returns "I don't have enough information".

### Secondary issues

1. **k parameter silently ignored**: Both `ainvoke()` calls pass `k=top_k * 2` as a kwarg, but `BaseRetriever.ainvoke()` doesn't forward kwargs to the underlying retrieval. BM25 always uses its default `k` (set at construction, defaults to 4).
2. **`retrieve()` handles None correctly**: The `_ensemble`-based `retrieve()` method only adds FAISS to the retriever list when available, so it works fine. But the route calls `retrieve_with_scores()` instead.

## Changes

### 1. `src/domain/services/retrieval_langchain.py`

**a) Set default `k` in BM25 construction:**
```python
self._bm25_retriever = BM25Retriever.from_documents(
    langchain_docs,
    k1=1.5,
    b=0.75,
    k=5,
)
```

**b) Fix `retrieve_with_scores` — guard against None FAISS and set k props directly:**
```python
async def retrieve_with_scores(self, question, question_embedding, top_k=5):
    if not self._index_built:
        return []

    try:
        bm25_k = top_k * 2
        self._bm25_retriever.k = bm25_k
        bm25_results = await self._bm25_retriever.ainvoke(question)
        bm25_scores = {}
        for i, doc in enumerate(bm25_results):
            chunk_id = doc.metadata.get("chunk_id", "")
            bm25_scores[chunk_id] = 1.0 / (i + 1)

        faiss_scores = {}
        faiss_results = []
        if self._faiss_vectorstore is not None:
            faiss_retriever = self._faiss_vectorstore.as_retriever()
            faiss_retriever.k = bm25_k
            faiss_results = await faiss_retriever.ainvoke(question)
            for i, doc in enumerate(faiss_results):
                chunk_id = doc.metadata.get("chunk_id", "")
                faiss_scores[chunk_id] = 1.0 / (i + 1)
        else:
            logger.info("FAISS vectorstore unavailable — using BM25 only for scoring")

        # ... rest unchanged: combine scores, MIN_RELEVANCE_SCORE threshold, return top_k

    except Exception as e:
        logger.error(f"Hybrid retrieval with scores failed: {type(e).__name__}: {e}")
        return []
```

### 2. `src/api/routes/query/routes.py`

Switch LangChain endpoint from `retrieve_with_scores` to `retrieve()` (the robust ensemble path):

```python
# Old:
retrieved = await hybrid_retriever.retrieve_with_scores(
    request.question, query_embedding, top_k=request.top_k,
)
# New:
retrieved = await hybrid_retriever.retrieve(
    request.question, top_k=request.top_k,
)
```

Same change in the streaming endpoint (`/langchain/stream`).

## Verification

```bash
uv run pytest tests/integration/test_rag_comparison.py -v -x
uv run pytest tests/integration/test_cache_bug.py -v -x
```
