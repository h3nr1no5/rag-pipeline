## Why

Chroma adds a redundant vector store that duplicates embeddings already stored in SQLite, adding ~3s to every document upload with zero benefit to response quality. The LlamaIndex backend's retrieval quality comes from its hybrid dense+BM25+RRF pipeline, cross-encoder reranker, and ResponseSynthesizer — none of which depend on Chroma. Removing Chroma simplifies the architecture, reduces upload latency, eliminates a heavy dependency (chromadb + llama-index-vector-stores-chroma), and removes the awkward pattern of dumping all nodes via an empty query just to build BM25.

## What Changes

- **Remove `_index_chunks_into_chroma()`** from `processor.py` — no more redundant indexing after chunking
- **Replace `ChromaVectorStore`** in the LlamaIndex backend with a SQLite-based node loader that reads `Chunk.embedding` + `Chunk.content` directly
- **Replace `VectorStoreIndex.as_retriever()`** for dense retrieval with an exact dot-product computation against SQLite embeddings (same as the cosine backend already does) — 100% recall vs. Chroma's ANN approximation
- **Remove Chroma deletion** from the document delete path in `documents.py`
- **Remove `chroma_persist_dir`** config option
- **Remove `chromadb` and `llama-index-vector-stores-chroma`** from dependencies
- **Delete `data/chromadb/`** directory (already-empty persistent Chroma storage)

## Capabilities

### New Capabilities
- `sqlite-llamaindex-vector-store`: Replace Chroma-backed `VectorStoreIndex` with a lightweight SQLite-backed node provider that serves chunks as `NodeWithScore` objects for the LlamaIndex retriever pipeline.

### Modified Capabilities
_(No existing spec files to modify — this is a pure implementation change.)_

## Impact

| Area | Impact |
|------|--------|
| `processor.py` | Remove `_index_chunks_into_chroma()` function and both callsites (~50 lines removed) |
| `llama_index_service.py` | Rewrite entire module: replace Chroma with SQLite-based node load/delete. No more `VectorStoreIndex`, no more `chromadb`. |
| `retrieval_llamaindex.py` | Replace `VectorStoreIndex.as_retriever()` dense retrieval with SQLite dot-product scan. Keep BM25, RRF, cross-encoder reranker, and ResponseSynthesizer unchanged. |
| `documents.py` | Remove Chroma deletion call (~10 lines removed) |
| `config.py` | Remove `chroma_persist_dir` setting |
| `pyproject.toml` | Remove `chromadb` and `llama-index-vector-stores-chroma` dependencies |
| `data/chromadb/` | Delete directory (no longer needed) |
| **Performance** | ~3s faster per upload (82 chunks), ~500KB disk space saved |
| **Quality** | **No change** — exact dot-product has 100% recall vs Chroma's ANN approximation |
