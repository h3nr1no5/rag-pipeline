## Why

The LangChain hybrid retriever produces unusable results because it uses a separate `HuggingFaceEmbeddings` wrapper for FAISS query embedding, while stored vectors were computed by the project's `SentenceTransformerEmbedder`. This creates a vector space mismatch — the same model name is loaded via two different code paths, with different normalization behavior and initialization, so queries live in a different vector space than the index. The result: FAISS retrieves irrelevant chunks and the LLM either hallucinates (empty context) or says "no information available."

Additionally, even when FAISS returns correct chunks, the actual similarity scores are discarded and replaced with rank-based `1/(rank+1)` scores, losing valuable semantic signal.

## What Changes

1. **Replace `HuggingFaceEmbeddings` with the project's embedder** — Make LangChain's FAISS vector store use `SentenceTransformerEmbedder` (via `get_embedder()`) for query encoding, so query embeddings match stored embeddings exactly.

2. **Use actual FAISS similarity scores** — Change FAISS retrieval to return real similarity scores via `similarity_search_with_relevance_scores()` instead of discarding them for rank-based scores.

3. **Cross-encoder score normalization** — After reranking, min-max normalize scores before applying the `min_relevance_score` threshold (same pattern already used by the cosine path).

4. **No changes to LlamaIndex** — Its hybrid retriever (RRF) uses `SentenceTransformerEmbedder` correctly via `get_embedder()` in `_dense_retrieve`. Only the LangChain path has the mismatch.

## Capabilities

### New Capabilities

- `langchain-retrieval`: Document the corrected LangChain hybrid retrieval behavior with proper embedding alignment, similarity scoring, and cross-encoder reranking.

### Modified Capabilities

_(No existing specs to modify — this is the first spec creation for this project.)_

## Impact

- **File changed**: `src/domain/services/retrieval_langchain.py` (core fix)
- **File changed**: `src/domain/services/chain_langchain.py` (minor: ensure chain uses corrected retriever)
- **No new dependencies** — `sentence-transformers` is already installed; no additional packages needed
- **No schema changes** — DB, APIs, and models unaffected
- **Behavior change**: LangChain queries now retrieve the same correct chunks as the cosine path
