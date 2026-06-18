## Context

The LlamaIndex RAG backend (`retrieval_llamaindex.py`) was refactored in commit `b99a5f7` to remove Chroma and load chunks directly from SQLite. The refactored code introduced three gaps compared to the working cosine similarity backend (`_retrieval.py`):

1. **No embedding validation**: The cosine backend validates every chunk's embedding (null, type, dimension, NaN, Inf) before computing dot products. The LlamaIndex retriever skips all validation.
2. **No NULL embedding filter**: The cosine backend's SQL query includes `embedding IS NOT NULL`. The LlamaIndex retriever does not.
3. **Fragile score normalization**: Min-max normalization is applied only to the top-k RRF results (typically 5 nodes). When the dense and BM25 retrievers return the same unique node, RRF produces a single score → normalization is skipped (max==min) → score (~0.016) stays below the `min_relevance_score` threshold (0.15) → empty results.

Additionally, the LlamaIndex backend lacks:
- Integration tests (unlike cosine and LangChain which have them)
- Detailed stage-level debug logging

## Goals / Non-Goals

**Goals:**
- Make the LlamaIndex retriever robust against null, mismatched, or corrupted embeddings (matching the cosine backend)
- Fix the edge case where identical RRF scores cause all results to be filtered out
- Add integration tests that verify end-to-end retrieval + generation
- Add debug logging at each retrieval stage for faster diagnosis

**Non-Goals:**
- Performance optimization of the retriever
- Changing the RRF fusion algorithm itself
- Adding new retrieval backends or strategies
- Modifying the cosine or LangChain backends
- Changing the shared `min_relevance_score` setting or its default

## Decisions

### Decision 1: Add embedding validation as a shared utility
- **Choice**: Extract embedding validation from `_retrieval.py` into a standalone function `validate_embedding()` in the `embedding.py` service module.
- **Rationale**: Both `_retrieval.py` and `retrieval_llamaindex.py` need the same validation logic. A shared function prevents future drift between backends. The validation checks (null, type, dimension, NaN, Inf) are identical across all RAG backends.
- **Alternative considered**: Duplicating validation in `retrieval_llamaindex.py`. Rejected because it creates maintenance burden — if the validation needs to change later, both files must be updated.

### Decision 2: Add `embedding IS NOT NULL` filter to SQL query
- **Choice**: Add `Chunk.embedding.isnot(None)` to the `select(Chunk)` query in `_ensure_components()`.
- **Rationale**: Matches the cosine backend's query. Avoids loading chunks that can't contribute to dense retrieval. The `_dense_retrieve` method already handles `node_emb is None` by assigning score 0.0, but it's wasteful to load them at all.
- **Alternative considered**: Handle only in code (existing `if node_emb is None: scores.append(0.0)`). Rejected because null-embedding chunks still participate in BM25 with potentially misleading keyword matches, and they dilute the embedding pool.

### Decision 3: Ensure minimum normalization window size
- **Choice**: In `_retrieve_and_rerank()`, after RRF but before min-max normalization, if `len(nodes) < 2` or if `max_s - min_s <= 1e-10`, assign the top node a score of 1.0 instead of skipping normalization.
- **Rationale**: The top-1 RRF result is always the most relevant node. If we can't normalize it meaningfully, it should still pass the relevance threshold. Assigning 1.0 when normalization is degenerate guarantees at least one result.
- **Alternative considered**: Changing `min_relevance_score` to 0.0 for the LlamaIndex backend. Rejected because it would allow genuinely low-relevance results through. Alternative considered: using rank-based scores (1/rank) instead of RRF scores for the fallback. Rejected because it changes the scoring semantics and makes debugging harder.

### Decision 4: Add stage-level debug logging
- **Choice**: Add `logger.debug()` statements at each stage: chunks loaded, embeddings validated, dense scores computed, BM25 results count, RRF result count, cross-encoder status, normalized scores, filtered results.
- **Rationale**: The LangChain backend has these (e.g., "No chunks above relevance threshold"). Without them, diagnosing failures requires adding logging at runtime.

### Decision 5: Integration tests at the route level
- **Choice**: Add an integration test file `tests/integration/test_llamaindex.py` that tests the full LlamaIndex streaming and non-streaming endpoints via `ASGITransport`, matching the pattern of existing integration tests.
- **Rationale**: Existing integration tests for cosine and LangChain verify end-to-end behavior. The LlamaIndex backend has none, which is how the regression in `b99a5f7` went undetected.
- **Alternative considered**: Unit tests only. Rejected because the interaction between multiple components (SQLite, HybridRetriever, _ResilientReranker, LLM) is best tested at the integration level.

## Risks / Trade-offs

- **[Risk] Embedding validation could reject legitimate chunks if validation is too strict**: The cosine backend already uses the same checks. Extracting to a shared utility ensures consistent behavior.
- **[Risk] Syncing embedding validation across backends creates a coupling point**: Mitigated by the shared `validate_embedding()` utility — changes propagate automatically.
- **[Risk] The normalization fallback (assign 1.0) may allow one low-quality result through**: Mitigated because the top RRF result IS the most relevant; and the LLM's prompt is built from all returned sources, not just the top one.
- **[Trade-off] Integration tests require a running LLM/embedder**: Existing integration tests handle this via `ASGITransport` with singleton lazy-loading. The LlamaIndex retriever creates `HybridRetriever` without the LLM, so retrieval-only tests work without a model.
