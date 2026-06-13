## Context

The LangChain RAG pipeline has a hallucination problem. The system uses BM25 + FAISS hybrid retrieval feeding context to a Qwen2.5-1.5B-Instruct-4bit LLM. Analysis revealed six contributing factors:

1. **Prompt contradiction** — `no_verbatim` says "Never include '[Source N]' labels" even when `include_citations=True`, directly conflicting with the citation instruction
2. **"In your own words" anti-pattern** — encourages the model to diverge from source text
3. **No retrieval quality gate** — `retrieve()` hardcodes `score=1.0` on all results; `MIN_RELEVANCE_SCORE` exists but is only used in `retrieve_with_scores()` which is never called by routes
4. **Temperature too high** — default 0.5 for a 1.5B model produces exploratory sampling
5. **Weak citation forcing** — conditional instruction; model decides what counts as "factual"
6. **No output verification** — no post-generation check that claims match sources

The full pipeline today:

```
Question → BM25+FAISS → RRF scoring → hardcoded score=1.0 → dedup → prompt → LLM (temp=0.5) → clean_response → answer
                                                     ↑
                                              no quality filter
```

## Goals / Non-Goals

**Goals:**
- Eliminate prompt contradictions that confuse the model
- Ensure only relevant chunks reach the LLM (relevance threshold + re-ranking)
- Force mandatory inline source citations for every factual claim
- Lower temperature to reduce creativity in factual responses
- Add post-generation verification that catches unsupported claims
- Maintain backward compatibility for all existing API consumers

**Non-Goals:**
- Model upgrade (deferred; the 1.5B model stays for now)
- Modifying the cosine-similarity or LlamaIndex backends (only LangChain)
- Changing the chunking strategy or document ingestion pipeline
- Adding streaming-specific verification (streaming endpoints get the same verification applied after full generation)

## Decisions

### D1: Prompt Restructuring

**Decision**: Fix the prompt contradiction by removing "Never include '[Source N]' labels" from `no_verbatim` when `include_citations=True`. Remove "in your own words". Add mandatory citation instruction.

**Current prompt** (simplified):
```
Answer questions based ONLY on the provided sources below.
If the answer cannot be determined... say "I don't know"

Cite the source number when making factual claims.    ← conditional
...
Do not reproduce the source text verbatim. Answer concisely in your own words.
Never include '[Source N]' labels in your answer.     ← ALWAYS present
```

**New prompt** (when `include_citations=True`):
```
Answer questions based ONLY on the provided sources below.
If the answer cannot be determined... say "I don't know"

CRITICAL — For EVERY factual statement you make, you MUST include
a source citation in brackets like [Source 1] immediately after the
statement. Example: "The capital of France is Paris [Source 1]."
If a statement is not supported by any source, you MUST NOT make it.
Do not guess or use outside knowledge.

Quote or closely paraphrase the sources. Do not add information
that is not present in the sources. It is better to say "I don't
know" than to make up information.
```

**Rationale**: The contradiction is a bug. Removing "in your own words" removes the explicit license to rephrase. The new instruction makes citation mandatory rather than optional, and adds negative reinforcement ("do not guess", "do not add information").

**Alternatives considered**: Structured output format (Evidence + Conclusion sections). Rejected because it adds complexity and the simpler instruction approach is likely sufficient when combined with other fixes.

### D2: Retrieval Quality Gating

**Decision**: Two-layer approach — (a) switch `retrieve()` to use proper scores with a threshold, (b) add a cross-encoder re-ranker.

**Layer 1 — Proper scoring with threshold**:
- Modify `LangChainRetriever.retrieve()` to use the same scoring logic as `retrieve_with_scores()`: `0.5 × BM25_score + 0.5 × FAISS_score`
- Apply `MIN_RELEVANCE_SCORE = 0.15` (increased from 0.1 for stricter filtering)
- This is a small change — the scoring logic already exists in `retrieve_with_scores()`

**Layer 2 — Cross-encoder re-ranker**:
- After initial BM25+FAISS ensemble retrieval (top_k=20), pass results through a cross-encoder
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80MB, fast on CPU)
- Re-rank the 20 results and keep top 5
- The cross-encoder computes a query-document relevance score for each pair, which is more accurate than the bi-encoder embedding similarity

```
Question → BM25+FAISS (top_k=20) → RRF → cross-encoder re-rank (top_5) → score threshold → LLM
                                              ↑
                                        new: ~100-200ms latency
```

**Implementation**:
- New class `CrossEncoderReRanker` in `retrieval_langchain.py`
- Lazy-loaded singleton (same pattern as LLM and embedder)
- Config entry: `RERANKER_MODEL` defaulting to `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Config entry: `RERANKER_ENABLED` (bool, default True) so it can be disabled

**Rationale**: Cross-encoders are significantly more accurate for relevance judgment than bi-encoders or BM25 because they process query and document together rather than encoding them independently. The MiniLM variant is small enough for CPU inference under 200ms.

**Alternatives considered**:
- Just the threshold without re-ranker: simpler but less accurate
- Using LLM as re-ranker: too slow and expensive for a 1.5B model
- MonoT5 re-ranker: better accuracy but larger model (~3GB)

### D3: Temperature Default

**Decision**: Lower default `llm_temperature` from `0.5` to `0.1`.

**Rationale**: For factual QA, greedy or near-greedy decoding produces the most grounded responses. 0.1 is low enough to be highly deterministic while still allowing a tiny amount of variation. The API already allows per-request override via the `temperature` field, so users can increase it if they want more creative responses.

**Config change**: `src/core/config.py` line 35: `llm_temperature: float = 0.1`

### D4: Citation Forcing

**Decision**: Mandatory inline citations enforced through prompt instruction, with post-processing validation.

**Prompt instruction** (already covered in D1): Every factual statement must end with `[Source N]`.

**Post-processing in `clean_response`**:
- Parse all `[Source N]` references from the response
- Validate that each `N` refers to a valid source index (1 to `prompt_sources`)
- If a sentence lacks a citation AND `include_citations=True`, flag it
- For sentences without citations, attempt retroactive matching: compute embedding similarity against source chunks; if above threshold, insert the best-matching source citation

**Edge cases**:
- Model puts citation at end of paragraph instead of after each sentence → accept (better than nothing)
- Model cites [Source 0] or [Source 99] → strip or replace with best match
- Model cites but the content doesn't match the source → not detectable at citation level (covered by verification in D5)

### D5: Claim Verification

**Decision**: Embedding-based verification pipeline. No extra LLM call.

**Architecture**:
```
Response text
    │
    ▼
Split into sentences (by sentence boundaries: . ! ? followed by space)
    │
    ▼
For each sentence:
    ├── Has [Source N] citation? → Verify the citation index is valid
    └── No citation? → Embed sentence, find best-matching source chunk
                        └── Cosine similarity < threshold (0.65)?
                            └── YES → Flag/remove sentence
                            └── NO  → Accept with retroactive citation
```

**Implementation**:
- New file: `src/domain/services/verification.py`
- New class `ResponseVerifier` with method `verify(response: str, sources: list) -> VerifiedResponse`
- Returns a `VerifiedResponse` dataclass:
  - `verified_text: str` — cleaned response with unsupported claims removed
  - `citations: list[dict]` — per-sentence citation mapping
  - `unsupported: list[str]` — sentences that were removed or flagged
  - `confidence: float` — overall confidence score (0.0-1.0)

**Integration point**: Called in `chain_langchain.py`'s `generate()` and `generate_stream()` methods, after LLM generation completes but before yielding the response.

**Config**:
- `VERIFICATION_ENABLED` (bool, default True)
- `VERIFICATION_SIMILARITY_THRESHOLD` (float, default 0.65)
- `VERIFICATION_REMOVE_UNSUPPORTED` (bool, default True — when True, strip unsupported claims; when False, flag them in metadata)

**Rationale**: Embedding-based verification is fast (no extra LLM call) and catches the most obvious hallucinations — where the model says something completely unrelated to the sources. The threshold of 0.65 is a starting point; it should be tuned on real data. The `confidence` score allows the UI to surface uncertainty to users.

**Limitations**:
- Semantic similarity ≠ factual support. A sentence could be on-topic but factually wrong ("sky is green" vs "sky is blue" both score high on sky color similarity)
- Short sentences may have unreliable embeddings
- Mitigation: the primary defense is citation forcing (D4); verification is a secondary safety net

### D6: Increased Retrieval Depth

**Decision**: Change the LangChain retriever to fetch `top_k=20` initially, then filter to the best `prompt_sources` (default 3-5) after re-ranking and thresholding.

**Rationale**: The current `top_k=5` limits the retriever to only 5 candidates. By fetching 20, the cross-encoder has more material to work with and can pick the truly best chunks. The LLM only sees the top 3-5 anyway.

**Implementation**: Pass `top_k=20` to the ensemble retriever internally, run re-ranker, then return the top `request.top_k` (default 5) results.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Cross-encoder adds 100-200ms latency per query | Medium | Make re-ranker configurable (RERANKER_ENABLED); benchmark to verify |
| Lower temperature (0.1) makes responses too rigid | Low | User can override via API; we test with real queries first |
| Verification false positives (removing valid claims) | Medium | Start with flag-only mode, tune threshold, then enable removal |
| Verification false negatives (missing hallucinations) | High | Embedding similarity is not perfect; mitigate with strong citation forcing as primary defense |
| Cross-encoder model download (~80MB) at first use | Low | Same pattern as LLM lazy-loading; log progress |
| Changes affect only LangChain backend, not cosine or LlamaIndex | Low | Intentional — user can compare backends to evaluate improvement |

## Open Questions

1. **Verification threshold**: What's the right cosine similarity threshold? Start at 0.65, but needs tuning on real queries. Add a flag-only mode first to collect data.
2. **Cross-encoder model**: `ms-marco-MiniLM-L-6-v2` is optimized for MS Marco (web search). Is it suitable for document chunk relevance? Consider testing with a few sample queries before finalizing.
3. **Streaming**: Current streaming endpoints generate the full response internally then yield tokens. Verification happens after full generation. Is the slight latency acceptable? Yes — verification adds <50ms.
4. **Cross-encoder device**: CPU only (current setup). Would GPU accelerate? The model is small enough that CPU is fine, but GPU support could be added later.
