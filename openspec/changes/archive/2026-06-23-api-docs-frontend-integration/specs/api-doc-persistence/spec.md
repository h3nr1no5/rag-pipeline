## ADDED Requirements

### Requirement: API doc extraction results SHALL be persisted to SQLite

The system SHALL store extracted API documentation data (domain objects, chunk graph, and embedding vectors) in a dedicated `api_doc_indexes` database table. This data SHALL survive server restarts and SHALL be used to rebuild in-memory indexes at startup without calling the embedder model.

#### Scenario: Store extraction results on successful processing
- **WHEN** a document with `engine_type="api-docs"` is processed successfully
- **THEN** the system SHALL insert or update a row in `api_doc_indexes` with:
  - `document_id` — referencing the processed document
  - `domain_data` — JSON with `interfaces`, `enums`, and `error_codes` arrays serialized from the domain objects
  - `graph_data` — JSON with `nodes` and `root_node_ids` from `serialize_chunk_graph()`
  - `embeddings` — JSON dict mapping `chunk_id → [float, ...]` with the computed embedding vectors
  - `embedding_dim` — integer dimension of the embedding vectors
- **AND** the document's `status` SHALL be set to `"completed"` and `processing_message` SHALL indicate API doc indexing succeeded

#### Scenario: Skip persistence when no embeddings
- **WHEN** the embedder model is unavailable during processing
- **THEN** the system SHALL still persist `domain_data` and `graph_data`
- **THEN** `embeddings` SHALL be `null` and `embedding_dim` SHALL be `null`
- **AND** the document SHALL still be queryable via BM25-only retrieval (embeddings rebuilt on first query)

### Requirement: In-memory indexes SHALL be rebuilt from persisted data on startup

The `ApiDocPipelineManager` SHALL load all rows from `api_doc_indexes` during application startup and rebuild in-memory BM25 and FAISS indexes from stored data.

#### Scenario: Startup rebuild with stored embeddings
- **WHEN** the application starts and `ApiDocPipelineManager.load_all_from_db()` is called
- **THEN** it SHALL query all `api_doc_indexes` rows
- **FOR EACH** row:
  - **THEN** it SHALL deserialize `graph_data` into a `ChunkGraph`
  - **THEN** it SHALL rebuild the `ApiBm25Index` from the `ChunkGraph` (no model needed)
  - **WHEN** `embeddings` is not null
    - **THEN** it SHALL rebuild the `ApiEmbeddingIndex` FAISS index from the stored embedding vectors via `load_embeddings()` (pure numpy, no embedder model calls)
  - **WHEN** `embeddings` is null
    - **THEN** the embedding index SHALL be skipped (BM25-only mode; first query triggers re-embedding)

#### Scenario: Embedding dimension mismatch on startup
- **WHEN** the stored `embedding_dim` does not match the current embedder model's dimension
- **THEN** the system SHALL log a warning
- **THEN** the stored embeddings SHALL NOT be loaded into FAISS
- **THEN** the document SHALL be indexed on-the-fly on first query (fallback to re-embedding)

### Requirement: ApiEmbeddingIndex SHALL support loading from stored vectors

The `ApiEmbeddingIndex` class SHALL expose a `load_embeddings()` method that rebuilds the FAISS index from a pre-computed dict of chunk_id → vector, without calling the embedder model.

#### Scenario: load_embeddings creates FAISS index from dict
- **WHEN** `load_embeddings({"chunk_1": [0.1, 0.2, ...], "chunk_2": [0.3, 0.4, ...]}, dim=384)` is called
- **THEN** the method SHALL create a new `faiss.IndexFlatIP(dim)`
- **THEN** it SHALL normalize all vectors using `faiss.normalize_L2()`
- **THEN** it SHALL add the normalized vectors to the index
- **THEN** `self.chunk_ids` SHALL be set to the list of chunk_ids in the same order
- **AND** no embedder model calls SHALL be made
