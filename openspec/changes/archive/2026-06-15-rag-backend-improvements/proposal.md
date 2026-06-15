## Why

The three RAG backends have diverged in quality, consistency, and correctness. The LangChain backend frequently returns empty responses due to overly aggressive response verification, the cosine backend uses unnormalized embeddings producing unreliable similarity scores, and the LlamaIndex backend is a custom implementation in name only — it does not use any actual LlamaIndex libraries, defeating its purpose as a comparative baseline. These issues erode trust in the RAG pipeline and make benchmark comparisons meaningless.

## What Changes

- **LangChain**: Replace bi-encoder sentence verification with cross-encoder verification (already loaded as a singleton), fix a destructive regex bug in `clean_response` that strips content alongside citations, and honor user-provided `top_k` instead of hardcoding 5
- **Cosine backend**: Normalize embeddings at storage time in `processor.py` so dot-product similarity equals true cosine similarity, add optional response verification, and normalize retrieval scores for consistency
- **LlamaIndex**: Full rewrite using actual LlamaIndex libraries (`llama-index-core` + `llama-index-vector-stores-chroma`). Fresh Chroma-backed index built alongside the existing SQLite pipeline. New retrieval (hybrid embedding + BM25 → cross-encoder reranking) and response synthesis pipeline using LlamaIndex's `ResponseSynthesizer` with a custom MLX LLM adapter.
- **All backends**: Consistent score semantics — min-max normalized to [0,1] range with configurable `min_relevance_score` threshold applied uniformly

## Capabilities

### New Capabilities
- `llamaindex-rewrite`: Full LlamaIndex integration with Chroma vector store, hybrid retrieval with cross-encoder reranking, and LlamaIndex-native response synthesis replacing the current custom implementation
- `embedding-normalization`: Normalized embeddings stored at processing time so all backends compute true cosine similarity with consistent vector spaces

### Modified Capabilities
<!-- No existing specs to modify — this is the first spec-driven change for the project -->

## Impact

| Area | Impact |
|------|--------|
| `pyproject.toml` | Add dependencies: `llama-index-core`, `llama-index-vector-stores-chroma`, `llama-index-postprocessor` |
| `src/domain/services/processor.py` | After chunking, also index nodes into Chroma; normalize embeddings before storage |
| `src/domain/services/retrieval_llamaindex.py` | Full rewrite — was custom, now uses real LlamaIndex retriever API |
| `src/api/routes/query/routes.py` | Update LlamaIndex route handler to use new service; update LangChain route to pass `top_k` |
| `src/domain/services/verification.py` | Use cross-encoder (BGE reranker) instead of bi-encoder cosine for sentence verification |
| `src/domain/services/prompt_builder.py` | Fix destructive `[Source N]` regex bug in `clean_response` |
| `src/domain/services/embedding.py` | Add option to return normalized embeddings |
| `src/api/routes/query/_retrieval.py` | Normalize scores, add optional verification |
| `src/core/config.py` | Add Chroma persistence path config |
| New: `src/domain/services/llama_index_service.py` | Index management, retrieval orchestration for LlamaIndex |
| New: `src/domain/services/mlx_llama_integration.py` | MLX → LlamaIndex LLM adapter |
| No change to | `src/domain/services/llm.py`, shared `build_prompt`/`clean_response` (LangChain and cosine still use them) |
