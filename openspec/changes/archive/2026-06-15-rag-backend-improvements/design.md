## Context

This project has three RAG backends sharing a common SQLite database of document chunks with pre-computed embeddings (`all-mpnet-base-v2`, 768d). The LangChain backend performs BM25+FAISS hybrid retrieval with cross-encoder reranking and a unique response verification step. The cosine backend uses raw dot-product similarity with link traversal. The LlamaIndex backend is a custom implementation that does not use actual LlamaIndex libraries.

Three defects motivated this change:
1. **LangChain verification drops paraphrases**: The bi-encoder sentence-level verifier removes good paraphrased sentences below the 0.55 cosine threshold, frequently collapsing answers to a generic fallback
2. **Unnormalized embeddings**: The embedder does not normalize, the cosine backend uses raw dot-product, and LangChain's `HuggingFaceEmbeddings` normalizes — three different vector spaces
3. **LlamaIndex is misnamed**: The "LlamaIndex" backend is a plain cosine retriever with a SQLite adapter, providing no comparative value

## Goals / Non-Goals

**Goals:**
- Fix LangChain response verification to use the cross-encoder instead of bi-encoder cosine
- Fix `clean_response` citation regex bug that destroys sentence content
- Make LangChain honor user-provided `top_k`
- Normalize all embeddings at storage time for consistent cosine similarity across backends
- Add optional response verification to cosine backend
- Normalize retrieval scores to [0,1] range with consistent `min_relevance_score` across all backends
- Rewrite the LlamaIndex backend using actual LlamaIndex libraries with Chroma vector store, hybrid retrieval, cross-encoder reranking, and LlamaIndex-native response synthesis

**Non-Goals:**
- Not changing the LangChain retrieval algorithm (BM25+FAISS+RRF stays)
- Not changing the cosine backend's link traversal feature
- Not migrating the other backends away from SQLite to Chroma
- Not changing the shared `build_prompt`/`clean_response` for LangChain and cosine backends
- Not adding a full CI/CD pipeline or Docker setup

## Decisions

### D1: Cross-encoder for LangChain verification (1c from exploration)
**Choice**: Replace bi-encoder cosine verification with the existing `BAAI/bge-reranker-v2-minicpm-layerwise` cross-encoder.
**Rationale**: The cross-encoder is already loaded as a singleton for reranking and produces more accurate relevance scores (joint encoding vs. independent embeddings). Paraphrases score higher because the cross-encoder sees the sentence and chunk together.
**Alternatives considered**:
- 1a (lower threshold 0.55→0.35): Fixes false negatives but doesn't address the fundamental embedding space mismatch
- 1b (normalize bi-encoder embeddings): Would help but cross-encoder is strictly more accurate
- **Chosen** 1c: Cross-encoder provides the best semantic matching with zero additional memory (already loaded)

### D2: Normalize embeddings at storage time (1B from exploration)
**Choice**: L2-normalize embeddings in `processor.py` before writing to SQLite, then use simple dot-product for similarity (which equals cosine on unit vectors).
**Rationale**: Normalizing once at storage time is cheaper than normalizing per-query. All backends can use simple dot-product and get true cosine similarity. This fixes the three-vector-space inconsistency.
**Impact**: 
- Cosine backend: Currently uses raw dot-product → will become true cosine similarity (scores will shift)
- LangChain backend: Uses `HuggingFaceEmbeddings` with `normalize_embeddings=True` → scores will be consistent with other backends
- Re-normalization: If normalized vectors are re-normalized, they remain unchanged (safe for idempotency)

### D3: Chroma vector store for LlamaIndex
**Choice**: Use `llama-index-vector-stores-chroma` with local file-based persistence.
**Rationale**: Chroma integrates natively with LlamaIndex, supports metadata filtering (required for `document_ids` scoping), persists to disk automatically, and requires no server or Docker. The `SimpleVectorStore` is simpler but doesn't persist by default.
**Alternatives considered**:
- FAISS (in-memory): Would need custom persistence logic
- Qdrant: Feature-rich but requires a running server
- SQLite adapter: We already have this, but it's custom and defeats the purpose of using LlamaIndex
- **Chosen** Chroma: Best balance of features, persistence, and simplicity

### D4: MLX LLM adapter for LlamaIndex
**Choice**: Create a lightweight `MLXLlamaIndexLLM` class wrapping `MLXLLM` that implements LlamaIndex's `LLM` abstract base.
**Rationale**: LlamaIndex's `ResponseSynthesizer` needs a compatible LLM. Rather than loading a second model, wrapping the existing MLX singleton keeps memory usage identical.
**Implementation**: The adapter implements `__init__`, `achat`, `stream_chat` by delegating to `MLXLLM.generate()` / `generate_stream()`. A custom tokenizer proxy exposes `get_text_embedding_batch` for embeddings.

### D5: LlamaIndex owns its response pipeline
**Choice**: LlamaIndex backend uses `ResponseSynthesizer` with custom prompt templates, not shared `build_prompt`.
**Rationale**: Full LlamaIndex integration means using its native response synthesis. The custom prompt template matches the shared one's constraints (plain text, source citations, length control) so the frontend sees consistent output.

### D6: Index lifecycle — build on document upload
**Choice**: After `processor.py` finishes chunking and embedding a document, also index those nodes into Chroma.
**Rationale**: Matches the existing pattern where the LangChain chain lazily rebuilds its FAISS index. Building eagerly on upload is simpler and ensures Chroma is always up to date. No migration from SQLite needed — start fresh.

### D7: Score normalization across all backends
**Choice**: Apply min-max normalization to retrieval scores, then filter by `min_relevance_score`.
**Rationale**: Without normalization, score magnitudes differ wildly (dot-product: ~0-100, reciprocal rank fusion: ~0-1). Min-max normalization creates a uniform [0,1] range where `min_relevance_score` has the same semantics across all backends.

## Risks / Trade-offs

- **[Risk] LangChain cross-encoder verification is slower** than bi-encoder cosine for sentence-level checks (each sentence requires a forward pass through the cross-encoder). **Mitigation**: Cross-encoder inference is on GPU (MLX) and typically sub-second for 3-5 sentences. If latency is a concern, add sentence batching.
- **[Risk] Chroma persistence directory grows** unboundedly with document volume. **Mitigation**: Chroma uses SQLite under the hood — roughly same storage profile as the existing SQLite DB. Add to `.gitignore` and consider a TTL or cleanup policy if needed.
- **[Risk] LlamaIndex dependencies add ~15MB** to the project. **Mitigation**: `llama-index-core` is relatively lightweight; Chroma bindings add the most weight. Trade-off accepted for proper LlamaIndex integration.
- **[Risk] Normalizing stored embeddings breaks existing cosine backend scores** — regression in query cache or app behavior. **Mitigation**: The cache key includes document IDs and strategy parameters but not embedding normalization state. Document a cache-invalidating change (or clear cache manually).
- **[Risk] LlamaIndex response output format may differ** from other backends. **Mitigation**: Custom prompt template enforces plain-text output matching the shared template's constraints. Test with integration tests comparing outputs.

## Open Questions

1. **Cache clearing**: Should we invalidate all cached query responses after embedding normalization changes scores?
2. **Chroma index rebuild**: After this change is deployed, existing users need to re-upload documents or run a one-time migration to populate Chroma. Should we provide a CLI migration command?
3. **LLM adapter detail**: Should `MLXLlamaIndexLLM` be a separate module (`mlx_llama_integration.py`) or live inside `retrieval_llamaindex.py`?
