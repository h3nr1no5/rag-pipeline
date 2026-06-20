## Context

The LangChain RAG backend has two independent gates that can block valid responses:

1. **Retrieval phase** — BM25 + FAISS hybrid retrieval → cross-encoder re-ranking → relevance filtering
2. **Generation phase** — LLM generates response → verification strips unsupported claims

The cross-encoder re-ranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) is trained on MS MARCO web search data, making it poorly suited for general document chunk relevance. Additionally, it replaces reciprocal rank fusion (RRF) scores (range 0.0–1.0) with raw logits, but the same `min_relevance_score = 0.15` filter applies to both — causing all chunks to be discarded when CE logits fall below this threshold.

The verification layer uses a cosine similarity threshold of 0.65 with `all-mpnet-base-v2` embeddings, which discards well-paraphrased or synthesized sentences that don't cosine-match any single source chunk at ≥0.65. When all sentences are removed, the fallback is the same "I don't have enough information" message.

These two independent failure modes combine to produce unreliable responses for queries where relevant information exists.

## Goals / Non-Goals

**Goals:**

- Replace the cross-encoder model with one better suited for general document relevance
- Normalize cross-encoder scores to [0, 1] so the 0.15 threshold is meaningful regardless of CE model
- Lower verification threshold to retain valid paraphrases and syntheses
- Update config defaults for both settings
- Maintain backward compatibility — no API contract changes

**Non-Goals:**

- No changes to the BM25 or FAISS retrieval algorithms themselves
- No changes to the prompt template or LLM model
- No changes to the default (cosine) or LlamaIndex backends
- No architectural changes to the singleton pattern or caching

## Decisions

### Decision 1: Swap CE model to `BAAI/bge-reranker-v2-minicpm-layerwise`

**Why:** The current `cross-encoder/ms-marco-MiniLM-L-6-v2` is trained on web search queries (MS MARCO), which biases it toward short query-passage pairs typical of search engines. The BGE reranker family is trained on a diverse set of retrieval tasks (MS MARCO + NLI + other datasets), making it more robust for general document chunk relevance scoring.

**Alternatives considered:**
- `BAAI/bge-reranker-v2-m3` (2.2GB): Better absolute performance, but 4x larger download and slower inference. Overkill for a 1.5B parameter pipeline.
- Keeping MS MARCO but tuning threshold: Doesn't fix the domain mismatch — scores are systematically low for document content.
- No re-ranking at all: Loses the quality improvement CE provides for ranking.

### Decision 2: Min-max normalize CE scores before filtering

**Why:** CE models output raw logits with no standardized range. Without normalization, the 0.15 threshold is an accidental number that happens to work (or not) depending on which CE model is configured. Min-max normalization scales scores to [0, 1], making the 0.15 threshold mean "at least 15% as relevant as the top chunk" — interpretable and robust across CE models.

**Alternatives considered:**
- Softmax normalization: Creates a probability distribution, but with small candidate sets (≤20) a single high score can dominate, artificially suppressing others.
- Keep RRF scores, use CE only for ordering: Preserves threshold correctness but loses CE's ability to filter out truly irrelevant chunks.
- No normalization: Leaves threshold calibration dependent on the CE model's arbitrary output scale.

### Decision 3: Verification threshold 0.55

**Why:** Cosine similarity of 0.65 with `all-mpnet-base-v2` embeddings sits at the boundary between "close paraphrase" and "reasonable synthesis." A threshold of 0.55 admits well-written synthesized answers (which may not match any single source chunk at ≥0.65) while still filtering out clearly unsupported claims (typically 0.05–0.30). This was confirmed by examining typical similarity ranges for different answer types.

## Risks / Trade-offs

- [Lower verification threshold] → Some weakly-supported claims may pass where they were previously caught. Mitigation: 0.55 still requires topical relevance; truly fabricated claims will score well below this.
- [New CE model download] → First inference after deployment will download ~500MB. Mitigation: This is a one-time cost; subsequent loads use HuggingFace cache.
- [Min-max normalization edge case] → If all CE scores are identical (unlikely in practice), normalization yields 0 for all values, filtering everything. Mitigation: Add a guard — if max == min, skip normalization and retain original scores.
- [CE model swap] → Scores from different models are not directly comparable. Since we also add normalization, this is mitigated.
