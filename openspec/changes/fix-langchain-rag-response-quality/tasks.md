## 1. Cross-encoder model swap

- [ ] 1.1 Update `reranker_model` default in `src/core/config.py` from `cross-encoder/ms-marco-MiniLM-L-6-v2` to `BAAI/bge-reranker-v2-minicpm-layerwise`
- [ ] 1.2 Verify the new model loads correctly via `CrossEncoderReRanker._ensure_model()` (first-use download)

## 2. Score normalization in retrieval

- [ ] 2.1 Add min-max normalization in `retrieval_langchain.py` `retrieve()` after cross-encoder re-ranking: compute `normalized = (score - min) / (max - min)` across the candidate set
- [ ] 2.2 Add edge-case guard: if all CE scores are identical (max == min), skip normalization and retain original scores
- [ ] 2.3 Apply the `min_relevance_score >= 0.15` threshold against normalized scores instead of raw logits

## 3. Verification threshold adjustment

- [ ] 3.1 Update `verification_similarity_threshold` default in `src/core/config.py` from `0.65` to `0.55`
- [ ] 3.2 Verify the threshold is picked up by `ResponseVerifier.verify()` (no code change needed — it reads from settings)

## 4. Test alignment

- [ ] 4.1 Update integration tests in `tests/integration/test_langchain_verification.py` that assert against 0.65 verification behavior — update to 0.55
- [ ] 4.2 Verify existing tests still pass: `uv run pytest tests/integration/test_langchain_verification.py -v`
- [ ] 4.3 Manually test a query that previously returned "I don't have enough information" to confirm fix
