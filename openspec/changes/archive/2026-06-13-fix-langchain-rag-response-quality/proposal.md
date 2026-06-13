## Why

The LangChain RAG backend incorrectly returns "I don't have enough information to answer this question" for queries where relevant information exists in the document corpus. Two root causes were identified:

1. **Cross-encoder score mismatch**: The re-ranker replaces well-calibrated RRF scores (0–1 range) with raw CE logits, but the same `min_relevance_score = 0.15` threshold is applied — causing all chunks to be filtered out when CE logits fall below 0.15.
2. **Verification threshold too aggressive**: The post-generation verifier uses a cosine similarity threshold of 0.65, which strips well-paraphrased or synthesized sentences. When all sentences are removed, the fallback response is "I don't have enough information to answer this question."

This degrades user trust and makes the LangChain backend unreliable compared to the default cosine backend.

## What Changes

- Replace the cross-encoder re-ranker model from `cross-encoder/ms-marco-MiniLM-L-6-v2` (web-search tuned) to `BAAI/bge-reranker-v2-minicpm-layerwise` (general-purpose document relevance)
- Add min-max normalization of cross-encoder scores before applying the relevance threshold filter, so the 0.15 threshold operates on a [0, 1] range regardless of CE model
- Lower the verification similarity threshold from 0.65 to 0.55 to retain good paraphrases and syntheses while still blocking unsupported claims
- Update config defaults accordingly

## Capabilities

### New Capabilities

- `hybrid-retrieval-reranking`: Cross-encoder re-ranking with score normalization for the LangChain hybrid retriever
- `response-verification`: Post-generation claim verification against source chunks

### Modified Capabilities

<!-- No existing specs to modify — these are new capabilities being introduced. -->

## Impact

**Affected files:**
- `src/domain/services/retrieval_langchain.py` — CE model swap + min-max normalization in `retrieve()`
- `src/domain/services/verification.py` — threshold change in `verify()`
- `src/core/config.py` — update `reranker_model` and `verification_similarity_threshold` defaults

**Dependencies:**
- `sentence-transformers` already installed (used by cross-encoder)
- `BAAI/bge-reranker-v2-minicpm-layerwise` will be downloaded on first use (~500MB)
