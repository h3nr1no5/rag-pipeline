## ADDED Requirements

### Requirement: FAISS embedding function SHALL conform to LangChain Embeddings interface

The `_ProjectEmbeddingFunction` adapter SHALL inherit from `langchain_core.embeddings.Embeddings` and implement both abstract methods (`embed_query` and `embed_documents`).

#### Scenario: Embeddings interface conformance

- **WHEN** `FAISS.from_embeddings()` receives a `_ProjectEmbeddingFunction` instance as the embedding function
- **THEN** `isinstance(embedding_function, Embeddings)` SHALL return `True`
- **THEN** the FAISS index SHALL be built without errors

#### Scenario: FAISS query succeeds

- **WHEN** `FAISS.asimilarity_search_with_relevance_scores()` is called with a query
- **THEN** the method SHALL return results (not raise an `Exception`)
- **THEN** the returned scores SHALL be based on L2 distance converted via `1 / (1 + distance)`

#### Scenario: embed_documents is never called during FAISS init

- **WHEN** `FAISS.from_embeddings()` is called with pre-computed embeddings
- **THEN** `embed_documents()` SHALL NOT be invoked by the FAISS constructor
- **THEN** `embed_documents()` MAY raise `NotImplementedError` if called directly

## MODIFIED Requirements

### Requirement: Backward compatible API

The system SHALL use `FAISS.from_embeddings()` to build the vector store with pre-computed database embeddings. The embedding function SHALL conform to LangChain's `Embeddings` interface.

#### Scenario: Existing callers unaffected

- **WHEN** `LangChainRetriever.retrieve()` is called
- **THEN** the return type and signature SHALL be identical to before the change
- **THEN** only the internal scoring and filtering SHALL differ
