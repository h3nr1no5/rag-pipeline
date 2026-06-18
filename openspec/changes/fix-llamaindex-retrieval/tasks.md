## 1. Extract shared embedding validation

- [ ] 1.1 Add `validate_embedding()` function to `src/domain/services/embedding.py` that checks: null, type, dimension match, NaN, Inf
- [ ] 1.2 Refactor `_retrieval.py` to use the new shared `validate_embedding()` function
- [ ] 1.3 Add unit tests for `validate_embedding()` in existing embedding test file

## 2. Fix LlamaIndex retriever SQL query

- [ ] 2.1 Add `Chunk.embedding.isnot(None)` filter to the `select(Chunk)` query in `_ensure_components()`
- [ ] 2.2 Load both filtered and total chunk counts for logging

## 3. Fix LlamaIndex retriever score normalization

- [ ] 3.1 In `_retrieve_and_rerank()`, after RRF fusion, handle degenerate normalization: when `len(nodes) < 2` or `max_s - min_s <= 1e-10`, assign top node score 1.0
- [ ] 3.2 Verify the fix ensures at least one source is returned when chunks exist

## 4. Add embedding validation to LlamaIndex dense retrieval

- [ ] 4.1 In `_dense_retrieve()`, validate each chunk's embedding using shared `validate_embedding()` before computing dot product
- [ ] 4.2 Log a warning with chunk count when invalid embeddings are encountered
- [ ] 4.3 Assign score 0.0 to chunks with invalid embeddings

## 5. Add stage-level debug logging

- [ ] 5.1 Add logger.debug() after chunk loading (count loaded, count with valid embeddings)
- [ ] 5.2 Add logger.debug() after dense retrieval (min/max/mean scores)
- [ ] 5.3 Add logger.debug() after BM25 retrieval (result count)
- [ ] 5.4 Add logger.debug() after RRF fusion (result count and score range)
- [ ] 5.5 Add logger.debug() after cross-encoder rerank (success or fallback)
- [ ] 5.6 Add logger.debug() after score normalization (min/max/mean)
- [ ] 5.7 Add logger.warning() when `min_relevance_score` filter removes all results (with count of eliminated nodes)

## 6. Add integration tests for LlamaIndex backend

- [ ] 6.1 Create `tests/integration/test_llamaindex.py` with setup fixtures (test DB, test document with chunks, valid embeddings)
- [ ] 6.2 Add test: non-streaming endpoint returns sources with valid scores
- [ ] 6.3 Add test: streaming endpoint yields sources followed by tokens
- [ ] 6.4 Add test: no documents returns error
- [ ] 6.5 Add test: empty retrieval returns "I don't have enough information" message
- [ ] 6.6 Add test: NULL embeddings are handled without crash
- [ ] 6.7 Run full test suite to verify no regressions
