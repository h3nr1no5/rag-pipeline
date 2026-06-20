## Why

The LlamaIndex RAG backend returns "I don't have enough information to answer this question" while the cosine similarity and LangChain backends return correct answers for the same query. The root cause is a gap in embedding validation and score normalization in the LlamaIndex retriever that other backends handle correctly. This erodes user trust — if one of three backends consistently fails, users switch away from it entirely.

## What Changes

- Add `embedding IS NOT NULL` filter to the LlamaIndex retriever's SQL query (matching the cosine backend)
- Add embedding validation (null check, type check, dimension match, NaN/Inf check) before computing dot products
- Fix score normalization to handle the edge case where all RRF scores are identical (single unique node in results)
- Add debug logging at each stage of retrieval to match the visibility of other backends
- Add integration tests for the LlamaIndex backend to prevent regressions

## Capabilities

### New Capabilities
- `llamaindex-retrieval`: Embedding validation, score normalization robustness, and observability for the LlamaIndex hybrid retriever

### Modified Capabilities
*(No existing specs to modify — first capability being spec'd)*

## Impact

- **Affected code**: `src/domain/services/retrieval_llamaindex.py` — embedding loading, validation, dot product computation, score normalization, and logging
- **Affected routes**: `src/api/routes/query/routes.py` — streaming LlamaIndex endpoint may need minor logging improvements (handler already exists)
- **Affected tests**: New `tests/integration/test_llamaindex.py` file for integration tests
- **No new dependencies** — all validation uses stdlib (`math.isnan`, `math.isinf`, `isinstance`)
- **No breaking changes** — strictly additive fixes that make the backend more robust
