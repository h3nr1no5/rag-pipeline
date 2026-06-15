## 1. Cross-Cutting: Embedding Normalization at Storage Time

- [x] 1.1 Add `normalize_embedding()` utility to `src/domain/services/embedding.py` that L2-normalizes a vector
- [x] 1.2 Update `processor.py` to L2-normalize chunk embeddings before storing in SQLite
- [x] 1.3 Update cosine backend's `_retrieval.py` dot-product computation — verify it works correctly with normalized vectors (dot product = cosine on unit vectors)
- [x] 1.4 Verify LangChain backend already normalizes (uses `HuggingFaceEmbeddings` with `normalize_embeddings=True`) — no change needed, just confirm idempotency
- [x] 1.5 Verify LlamaIndex backend cosine computation works correctly with pre-normalized embeddings (redundant normalization is harmless)
- [x] 1.6 Add config constant for embedding normalization (in case disable is needed), default to enabled

## 2. Cross-Cutting: Score Normalization and Consistent Thresholds

- [x] 2.1 Add `normalize_scores()` utility function to shared helpers that applies min-max normalization to a list of scores
- [x] 2.2 Apply min-max normalization in cosine backend (`_retrieval.py`) before filtering by `min_relevance_score`
- [x] 2.3 Apply min-max normalization in LlamaIndex backend (`retrieval_llamaindex.py`) before filtering — replace hardcoded `0.01` with `settings.min_relevance_score`
- [x] 2.4 Verify LangChain backend already applies min-max normalization (no regression)
- [x] 2.5 Add integration tests verifying all three backends return [0,1] scores

## 3. LangChain: Fix Response Verification

- [x] 3.1 Refactor `verification.py` `ResponseVerifier.verify()` to use the existing cross-encoder singleton (`CrossEncoderReRanker` from `retrieval_langchain.py`) instead of bi-encoder cosine similarity for sentence-level verification
- [x] 3.2 Update the verifier's similarity threshold to work with cross-encoder scores (different range from cosine — may need tuning, document the chosen value)
- [x] 3.3 Add integration test for LangChain verification: query that previously returned empty/generic response should now return substantive answer

## 4. LangChain: Citation Regex Bug and top_k

- [x] 4.1 Fix `clean_response()` in `prompt_builder.py` line 173 — replace destructive regex `r'\[Source \d+\].*?(?=\.|$)'` with targeted pattern that removes only the citation marker itself, not following content
- [x] 4.2 Update `chain_langchain.py` to accept and forward `top_k` parameter from request (currently hardcoded to 5)
- [x] 4.3 Pass `request.top_k` through route handler in `routes.py` to LangChain QA chain

## 5. Cosine Backend: Add Optional Response Verification

- [x] 5.1 Add an optional verification step to the cosine backend's response pipeline, reusing the `ResponseVerifier` from `verification.py` (gated by `settings.verification_enabled`)
- [x] 5.2 Wire verification into `routes.py` non-streaming and streaming handlers for the cosine backend
- [x] 5.3 Add integration test for cosine backend with verification enabled

## 6. LlamaIndex Rewrite: Dependencies and Infrastructure

- [x] 6.1 Add `llama-index-core`, `llama-index-vector-stores-chroma`, and `llama-index-postprocessor` to `pyproject.toml`
- [x] 6.2 Add `CHROMA_PERSIST_DIR` config to `src/core/config.py` (default: `data/chromadb/`)
- [x] 6.3 Create `src/domain/services/mlx_llama_integration.py` with `MLXLlamaIndexLLM` adapter class wrapping `MLXLLM` (implement `LLM` abstract base: `__init__`, `achat`, `stream_chat`, text embedding passthrough)
- [x] 6.4 Create `src/domain/services/llama_index_service.py` with index management (build/update/delete from Chroma)

## 7. LlamaIndex Rewrite: Retriever and Response Pipeline

- [x] 7.1 Rewrite `retrieval_llamaindex.py`: implement `LlamaIndexRetriever` using `VectorStoreIndex` backed by Chroma, with metadata filtering for `document_ids`
- [x] 7.2 Add hybrid retrieval: embedding similarity + BM25 keyword search fused via reciprocal rank fusion
- [x] 7.3 Add cross-encoder reranking step (use existing `CrossEncoderReRanker` singleton)
- [x] 7.4 Implement response synthesis using LlamaIndex's `ResponseSynthesizer` with a custom prompt template matching the project's constraints (plain text, source citations, length control)
- [x] 7.5 Wire new retriever and synthesis into route handlers in `routes.py` (non-streaming and streaming `POST /api/v1/query/llamaindex`)
- [x] 7.6 Update `processor.py` to index document nodes into Chroma after chunking

## 8. LlamaIndex Rewrite: Index Lifecycle and Cleanup

- [x] 8.1 Add document deletion from Chroma index when a document is removed
- [-] 8.2 ~~One-time migration entrypoint: scan existing SQLite chunks and index into Chroma (CLI command or startup check)~~ — DECIDED: start fresh, no migration needed
- [x] 8.3 Ensure `data/chromadb/` is in `.gitignore`

## 9. Testing and Validation

- [x] 9.1 Run existing test suite (`uv run pytest -v`) — confirm no regressions from embedding normalization
- [x] 9.2 Run LangChain integration tests — confirm verification fix returns substantive answers
- [x] 9.3 Run LlamaIndex integration tests — confirm new implementation works end-to-end
- [x] 9.4 Manual smoke test: query all three backends with same question and compare response quality
