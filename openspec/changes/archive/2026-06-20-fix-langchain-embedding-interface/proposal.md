## Why

The LangChain hybrid retrieval path (`POST /api/v1/query/langchain` and `/langchain/stream`) silently returns empty results for every query. The root cause is `_ProjectEmbeddingFunction` — the FAISS embedding adapter created in the fix-faiss-embedding-mismatch change — does not inherit from LangChain's `Embeddings` base class. In LangChain >=0.3, `FAISS.similarity_search_with_relevance_scores()` now enforces this at runtime, raising an exception that causes `retrieve()` to return no chunks. The LLM then responds "I don't have enough information" because no context was provided.

This makes the LangChain backend entirely non-functional. The cosine and LlamaIndex backends are unaffected.

## What Changes

- `_ProjectEmbeddingFunction` in `src/domain/services/retrieval_langchain.py` will inherit from `langchain_core.embeddings.Embeddings`
- `embed_documents()` will be implemented (required by the abstract interface; raises `NotImplementedError` since pre-computed embeddings are used during `FAISS.from_embeddings()`)
- `embed_query()` already exists and satisfies the interface — no changes needed
- No API surface changes, no new dependencies, no configuration changes

## Capabilities

### New Capabilities

*(none — this is a bug fix to an existing capability)*

### Modified Capabilities

- `hybrid-retrieval-reranking`: The `_ProjectEmbeddingFunction` FAISS adapter MUST conform to LangChain's `Embeddings` abstract interface (`embed_query` + `embed_documents`). This is a requirement that was implicitly assumed but never enforced; LangChain >=0.3 now validates it at runtime.

## Impact

- **Code**: Only `src/domain/services/retrieval_langchain.py` (the `_ProjectEmbeddingFunction` class, ~2 lines changed)
- **Dependencies**: None added. `langchain_core.embeddings.Embeddings` is already available via `langchain>=0.3`
- **Tests**: The existing `test_rag_comparison.py` and `test_score_normalization.py` integration tests should pass after this fix. No new tests needed for the interface conformance itself — the fix is validated by the existing tests passing.
