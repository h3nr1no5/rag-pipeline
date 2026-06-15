## Context

The LlamaIndex RAG backend currently depends on Chroma as an auxiliary vector store. During document upload, embeddings are saved to SQLite (`Chunk.embedding`) and then redundantly indexed into Chroma via `_index_chunks_into_chroma()`. At retrieval time, the  LlamaIndex backend reads embeddings from Chroma for dense retrieval, while all other retrieval quality features (BM25, RRF fusion, cross-encoder reranking, ResponseSynthesizer) operate on node text independent of Chroma.

The 768-d embeddings are L2-normalized before storage in both locations (normalization enabled in config). Chroma's HNSW ANN index provides approximate nearest-neighbor search that is functionally equivalent to — but slightly less accurate than — an exact dot-product scan against the same vectors in SQLite.

## Goals / Non-Goals

**Goals:**
- Eliminate Chroma as a dependency: remove `chromadb` and `llama-index-vector-stores-chroma`
- Remove the redundant `_index_chunks_into_chroma()` step from document processing (saves ~3s/upload)
- Replace Chroma-backed dense retrieval in `LlamaIndexRetriever` with exact dot-product from `Chunk.embedding` in SQLite
- Simplify the architecture: remove `LlamaIndexService` singleton entirely, inline node loading into the retriever
- Maintain identical retrieval quality — exact cosine similarity matches or exceeds Chroma's ANN recall
- Keep the LlamaIndex backend fully functional: hybrid retrieval, cross-encoder reranker, ResponseSynthesizer unchanged

**Non-Goals:**
- Changing BM25, RRF fusion, cross-encoder reranker, or ResponseSynthesizer behavior
- Changing the cosine or LangChain RAG backends (they already read from SQLite)
- Altering the document processing embedding/save loop (batch embedding and WAL mode are handled by a separate change)
- Removing LlamaIndex as a dependency (we still need `NodeWithScore`, `ResponseSynthesizer`, `RetrieverQueryEngine`, `BaseRetriever`, `PromptTemplate`)

## Decisions

### D1: Remove `LlamaIndexService` and inline into `LlamaIndexRetriever`

**Decision:** Delete `llama_index_service.py`. The `LlamaIndexRetriever` will load chunks directly from SQLite in its `_ensure_engine()` method.

**Rationale:**
- The service existed solely to manage the Chroma-backed `VectorStoreIndex` singleton
- Without Chroma, there is no index to manage — chunks are always queryable from SQLite
- Inlining avoids an unnecessary indirection layer and eliminates the `get_llama_index_service()` singleton
- Each `LlamaIndexRetriever` instance already has its own `_ensure_engine()` lazy-init pattern

**Alternatives considered:**
- *Keep service as a SQLite-backed node store* — adds unnecessary abstraction over a simple SQL query
- *Keep the singleton for the retriever instance* — retrievers are created per-request by `get_llamaindex_retriever()`, no singleton needed

### D2: Replace `VectorStoreIndex.as_retriever()` with SQLite dot-product scan

**Decision:** In `HybridRetriever`, replace `self._vector_index.as_retriever().aretrieve(query)` with a `_dense_retrieve(query, nodes, top_k)` method that:
1. Embeds the query using `get_embedder()` + `normalize_embedding()` (reuses existing infrastructure)
2. Computes dot-product against every node's embedding (stored alongside nodes during initialization)
3. Returns top-k as `NodeWithScore[]`

**Rationale:**
- Exact dot-product on normalized vectors = cosine similarity with 100% recall
- At ~82 chunks per document, a full scan is faster than HNSW index traversal with no quality loss
- Embeddings are already normalized and stored in `Chunk.embedding` — no transformation needed
- Reuses the same `get_embedder()` and `normalize_embedding()` paths the cosine backend uses
- Avoids the empty-query dump hack (`retriever.aretrieve("")`) that Chroma required (line 147)

### D3: Load all chunks upfront during `_ensure_engine()`

**Decision:** When `LlamaIndexRetriever._ensure_engine()` initializes, it queries `SELECT * FROM chunks WHERE document_id IN (...) ORDER BY chunk_index` and keeps all rows in memory as a list of `(NodeWithScore, embedding)` pairs.

**Rationale:**
- The current code already loads all nodes via `aretrieve("")` — this replaces that with a proper SQL query
- The node list is needed for BM25 index construction (requires full text corpus)
- The embeddings are needed for dense retrieval (requires dot-product against all)
- Document-level filtering is no longer done in Python — the WHERE clause handles it at the DB level (fixes a subtle bug in the current code where `aretrieve("")` returns ALL documents' nodes, then Python-filters by document_id)

**Memory concern:** 82 chunks × ~1KB text = ~82KB nodes + 82 × 768 × 4 bytes = ~250KB embeddings ≈ 350KB total. Trivial.

### D4: Convert Chroma deletion to no-op

**Decision:** Document deletion via `documents.py` already cascades to `Chunk` rows in SQLite. Since the retriever reads from SQLite, there is nothing extra to delete. Remove the Chroma deletion call entirely.

**Rationale:** SQLAlchemy cascade handles chunk deletion when a document is deleted. No vector store cleanup needed.

### D5: Keep `NodeWithScore` structure identical

**Decision:** The `NodeWithScore` objects created from SQLite will have the same metadata schema as the current Chroma-backed nodes:
- `node_id` → `chunk.id`
- `text` → `chunk.content`
- `metadata` → `{document_id, chunk_index, chunk_id, ...chunk.chunk_metadata}`

**Rationale:** BM25, cross-encoder reranker, and ResponseSynthesizer all read from these fields. Changing them would cascade through the pipeline. Zero schema change needed.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Forgetting to embed query before dot-product | Dense retrieval returns 0s | Embedding step is explicit in `_dense_retrieve()` — visible in code review |
| `chunk.embedding` is None for some chunks | Dot-product returns 0 score, chunk excluded | Query should handle `None` gracefully (skip with score 0.0, not crash) |
| Non-normalized embeddings break cosine equivalence | Retrieval quality degrades | Normalization is already enabled by default (`embedding_normalization_enabled: True`) and tested via `test_score_normalization.py` |
| Large document (1000+ chunks) makes full scan slow | ~3ms per 1000 dot products via numpy | At current scale (82 chunks) this is ~0.25ms. Future optimization: optional numpy vectorization |
| `NodeWithScore` constructor changes in a LlamaIndex upgrade | Build breaks | Pin `llama-index-core` version; tests catch schema changes |
| BM25 index rebuilt on every retriever instantiation | Adds ~2ms per query | Acceptable at current scale. Could cache by document_id set if needed later |

## Migration Plan

**Phase 1 — Core refactor (working LlamaIndex without Chroma):**
1. Rewrite `llama_index_service.py` → replace with `SqliteNodeLoader` module (or inline into retriever)
2. Refactor `retrieval_llamaindex.py` — add `_dense_retrieve()`, remove `VectorStoreIndex` usage
3. Remove `_index_chunks_into_chroma()` from `processor.py`
4. Remove Chroma deletion from `documents.py`

**Phase 2 — Cleanup:**
5. Remove `chroma_persist_dir` from `config.py`
6. Remove `chromadb` and `llama-index-vector-stores-chroma` from `pyproject.toml`
7. Delete `data/chromadb/` directory
8. Update test fixtures that reference Chroma

**Rollback:** Revert the change via `git revert`. All data is preserved in SQLite; no data migration needed.

## Open Questions

- None — the design is fully determined by the existing SQLite schema and LlamaIndex API surface.
