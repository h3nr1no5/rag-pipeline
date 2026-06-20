## 1. Configuration Setup

- [x] 1.1 Add `RERANKER_MODEL` setting to `Settings` class in `src/core/config.py` (default: `"cross-encoder/ms-marco-MiniLM-L-6-v2"`)
- [x] 1.2 Add `RERANKER_ENABLED` setting to `Settings` class (default: `True`)
- [x] 1.3 Add `VERIFICATION_ENABLED` setting to `Settings` class (default: `True`)
- [x] 1.4 Add `VERIFICATION_SIMILARITY_THRESHOLD` setting to `Settings` class (default: `0.65`)
- [x] 1.5 Add `VERIFICATION_REMOVE_UNSUPPORTED` setting to `Settings` class (default: `True`)

## 2. Temperature Tuning

- [x] 2.1 Change `llm_temperature` default in `src/core/config.py` from `0.5` to `0.1`
- [x] 2.2 Update `.env.example` to reflect new default temperature

## 3. Prompt Grounding

- [x] 3.1 Fix prompt contradiction in `build_prompt()`: when `include_citations=True`, do NOT include "Never include '[Source N]' labels in your answer" from `no_verbatim`
- [x] 3.2 Replace "Answer concisely in your own words" with "Quote or closely paraphrase the sources"
- [x] 3.3 Replace weak citation instruction with mandatory citation instruction: "For EVERY factual statement you make, you MUST include a source citation in brackets like [Source 1] immediately after the statement. If a statement is not supported by any source, you MUST NOT make it. Do not guess or use outside knowledge."
- [x] 3.4 Add negative reinforcement: "Do not add information that is not present in the sources. It is better to say 'I don't know' than to make up information."
- [x] 3.5 Remove the `no_verbatim` variable entirely and inline the remaining instruction without the citation contradiction
- [x] 3.6 Citation validation implemented in `ResponseVerifier._validate_citation_indices()` — parses `[Source N]` references, validates indices (1 to `num_sources`), replaces invalid with best-matching source
- [x] 3.7 Retroactive citation matching implemented in `ResponseVerifier.verify()` — for sentences without citations (when `include_citations=True`), finds best-matching source chunk via embedding similarity

## 4. Retrieval Quality Gating

- [x] 4.1 Modify `LangChainRetriever.retrieve()` to compute proper scores (0.5 * BM25_rank_score + 0.5 * FAISS_rank_score) instead of hardcoding `score=1.0`
- [x] 4.2 Apply `MIN_RELEVANCE_SCORE = 0.15` threshold in `retrieve()` (increase from unused 0.1)
- [x] 4.3 Add `CrossEncoderReRanker` class as lazy-loaded singleton in `retrieval_langchain.py`
- [x] 4.4 Implement re-ranking logic: take top 20 from ensemble retriever, score with cross-encoder, return top `request.top_k`
- [x] 4.5 Wire cross-encoder re-ranker into `retrieve()` method: fetch top 20, re-rank, apply threshold, return top k
- [x] 4.6 Add graceful fallback: if cross-encoder fails to load or `RERANKER_ENABLED=False`, fall back to ensemble retrieval without re-ranking
- [x] 4.7 No new dependency needed: `sentence-transformers` already in project (CrossEncoder from sentence_transformers)

## 5. Response Verification

- [x] 5.1 Create new file `src/domain/services/verification.py`
- [x] 5.2 Implement `VerifiedResponse` dataclass: `verified_text`, `citations`, `unsupported`, `confidence`
- [x] 5.3 Implement `ResponseVerifier` class with `verify(response, sources) -> VerifiedResponse`
- [x] 5.4 Implement sentence splitting logic (split on `. ! ?` followed by space/newline)
- [x] 5.5 Implement per-sentence embedding comparison against source chunks using embedder
- [x] 5.6 Implement unsupported claim removal or flagging based on `VERIFICATION_REMOVE_UNSUPPORTED`
- [x] 5.7 Implement empty response fallback: when all claims removed, return "I don't have enough information to answer this question."
- [x] 5.8 Handle `VERIFICATION_ENABLED=False` path (skip verification, return raw response)

## 6. Integration into LangChain Chain

- [x] 6.1 Wire `ResponseVerifier` into `LangChainQAChain.generate()` — call `verify()` after LLM generation, return `verified_text`
- [x] 6.2 Wire `ResponseVerifier` into `LangChainQAChain.generate_stream()` — collect full response, verify, then yield
- [x] 6.3 Ensure source chunks used in the prompt are passed to the verifier
- [x] 6.4 Update `LangChainRetriever.retrieve()` callers in LangChain route handlers to use the improved method

## 7. Testing

- [ ] 7.1 Write unit tests for prompt builder changes (contradiction fix, new instructions, citation validation)
- [ ] 7.2 Write unit tests for retrieval quality gating (proper scores, threshold filtering, cross-encoder re-ranking)
- [x] 7.3 Write unit tests for `ResponseVerifier` (supported claims, unsupported claims, empty response, configuration)
- [x] 7.4 Write integration test for full LangChain pipeline with all improvements enabled
- [x] 7.5 Run existing test suite to verify no regressions (30 unit tests pass, 8 of 10 integration tests pass - 2 pre-existing failures)
- [ ] 7.6 Manual verification: compare LangChain responses before vs. after changes with sample queries

## 8. Documentation & Cleanup

- [x] 8.1 Update `.env.example` with new configuration entries
- [x] 8.2 Review code for any unused imports or dead code (e.g., `no_verbatim` variable, old `retrieve_with_scores` duplication)
