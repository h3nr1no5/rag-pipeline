## MODIFIED Requirements

### Requirement: LlamaIndex owns its response pipeline

The LlamaIndex backend SHALL construct its response prompt using the shared `build_prompt()` from `prompt_builder.py` instead of LlamaIndex's `ResponseSynthesizer`. The backend owns its response pipeline by routing through the shared `get_llm()` singleton and `clean_response()`, not through proprietary LlamaIndex synthesis components.

**Note:** This requirement was originally written for the Chroma-backed architecture (commit `b99a5f7`) where `generate()` used `RetrieverQueryEngine` with `ResponseSynthesizer`. After the Chroma removal (commit `c505d74`), the architecture was rewritten to construct prompts manually. This update reflects the current architecture — the LlamaIndex backend no longer uses `ResponseSynthesizer`.

#### Scenario: Response synthesis uses shared prompt builder

- **WHEN** `LlamaIndexRetriever.generate()` is called
- **THEN** the backend SHALL use `build_prompt()` from `prompt_builder.py` for prompt construction
- **AND** route response generation through the shared `get_llm()` singleton

#### Scenario: Custom prompt template produces compatible answers

- **WHEN** the LlamaIndex backend generates a response
- **THEN** the output SHALL be plain text (no markdown formatting) matching the format of other backends

## REMOVED Requirements

### Requirement: Index built during document processing

**Reason:** The Chroma-backed architecture was removed. Indexing is now handled by the SQLite-backed hybrid retriever which loads chunks directly from the database at query time — no persistent index build is needed.

**Migration:** No migration needed. Chunks are stored in SQLite with embeddings. The `LlamaIndexRetriever` loads them at query time via `_ensure_components()`.

### Requirement: Chroma vector store for index persistence

**Reason:** Chroma was removed in commit `c505d74`. The LlamaIndex backend now uses SQLite-stored embeddings for dense retrieval and a BM25 index built in-memory from the loaded chunks for sparse retrieval.

**Migration:** No migration needed. Embeddings are stored in the `Chunk.embedding` column and loaded on demand.

### Requirement: Index updated during document processing

**Reason:** With the SQLite-backed retriever, there is no separate index to update. Chunks are loaded fresh from the database on each query. Document processing writes chunks to SQLite as before.

**Migration:** No changes needed to document processing.
