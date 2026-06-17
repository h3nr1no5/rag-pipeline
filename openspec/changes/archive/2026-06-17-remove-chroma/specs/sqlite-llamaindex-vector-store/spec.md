## ADDED Requirements

### Requirement: Chunks loadable from SQLite as LlamaIndex NodeWithScore objects

The LlamaIndex retriever SHALL load chunks from SQLite directly by querying the `Chunk` table for the requested `document_id`s, and SHALL construct `NodeWithScore` objects with an identical metadata schema to the previous Chroma-backed nodes.

- `node_id` SHALL be set to `Chunk.id`
- `text` SHALL be set to `Chunk.content`
- `metadata` SHALL contain: `document_id`, `chunk_index`, `chunk_id`, plus all key-value pairs from `Chunk.chunk_metadata`
- The query SHALL use a `WHERE document_id IN (...)` clause for document-level filtering (replacing the previous in-Python filter over all nodes)
- Nodes SHALL be ordered by `chunk_index` for deterministic BM25 index construction

#### Scenario: Load chunks for a single document
- **WHEN** `LlamaIndexRetriever._ensure_engine()` is called with `document_ids=["doc-1"]`
- **THEN** it loads all `Chunk` rows with `document_id="doc-1"` from SQLite and creates `NodeWithScore` objects with correct `node_id`, `text`, and `metadata`

#### Scenario: Load chunks for multiple documents
- **WHEN** `LlamaIndexRetriever._ensure_engine()` is called with `document_ids=["doc-1", "doc-2"]`
- **THEN** it loads all `Chunk` rows matching either document_id and creates `NodeWithScore` objects for both

#### Scenario: Metadata structure preserved
- **WHEN** a `NodeWithScore` is created from a SQLite `Chunk`
- **THEN** `node.metadata` contains: `document_id`, `chunk_index`, `chunk_id`, and all entries from `chunk.chunk_metadata`

### Requirement: Document processing does NOT index into Chroma

The document processing pipeline in `processor.py` MUST NOT call any Chroma indexing function after chunking and embedding chunks. The `_index_chunks_into_chroma()` function SHALL be removed entirely.

- The processor SHALL save chunks to SQLite only
- No additional vector store indexing step SHALL follow the save loop

#### Scenario: Process a document without Chroma index
- **WHEN** a document is processed through `process_document_async()`
- **THEN** no calls to Chroma or any Chroma-related function are made during processing
- **AND** the document is correctly marked as `completed` in SQLite

#### Scenario: LlamaIndex retriever works without prior Chroma indexing
- **WHEN** a document is processed (without Chroma indexing) and then queried via `LlamaIndexRetriever`
- **THEN** the retriever loads chunks from SQLite and returns correct results

### Requirement: Dense retrieval uses exact dot-product on SQLite embeddings

The `HybridRetriever` SHALL perform dense retrieval by computing an exact dot-product between the query embedding and all chunk embeddings stored in SQLite. This replaces the previous `VectorStoreIndex.as_retriever()` call against Chroma's HNSW index.

- The query embedding SHALL be computed using `get_embedder().embed_text()` and normalized using `normalize_embedding()` if `embedding_normalization_enabled` is True
- Dot-product on L2-normalized vectors SHALL be used as the similarity metric (equivalent to cosine similarity)
- Chunks with `embedding IS NULL` SHALL be assigned a score of 0.0 and not excluded from results
- The top-k results SHALL be returned as `NodeWithScore[]` with `score` set to the dot-product value
- K SHALL default to 20 (matching the current `similarity_top_k` value)

#### Scenario: Dense retrieval returns top-k by similarity
- **WHEN** `HybridRetriever._aretrieve("What is RAG?")` is called
- **THEN** the query is embedded, dot-product is computed against all chunk embeddings, and the top-k chunks (by score) are returned as `NodeWithScore` objects

#### Scenario: Empty query handled gracefully
- **WHEN** `HybridRetriever._aretrieve("")` is called (empty query)
- **THEN** the query embedding is all zeros (or near-zero), dot-products are all near-zero, and the top-k results are returned in arbitrary order (no crash)

#### Scenario: Null embeddings handled without error
- **WHEN** a chunk has `embedding IS NULL`
- **THEN** it is skipped with score 0.0 — the retrieval does not crash or raise an error

### Requirement: Document deletion does NOT require Chroma cleanup

When a document is deleted via the API, the system MUST NOT attempt to delete from Chroma. SQLite cascade deletion of `Chunk` rows is sufficient.

#### Scenario: Delete document without Chroma call
- **WHEN** a document is deleted via `DELETE /api/v1/documents/{document_id}`
- **THEN** the handler does not call any Chroma deletion function
- **AND** the document and its chunks are deleted from SQLite via existing cascade

### Requirement: Chroma dependencies removed from project

The project SHALL remove all Chroma-related Python package dependencies from `pyproject.toml`:
- `chromadb` SHALL be removed
- `llama-index-vector-stores-chroma` SHALL be removed
- The `chroma_persist_dir` config setting in `config.py` SHALL be removed
- The `data/chromadb/` directory SHALL be deleted

#### Scenario: Chroma packages not importable
- **WHEN** the project dependencies are installed via `uv sync`
- **THEN** `import chromadb` raises `ModuleNotFoundError`
- **AND** all retrieval backends (cosine, LangChain, LlamaIndex) still function correctly
