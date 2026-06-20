# Hybrid Retrieval Reranking

## Purpose

Improve LangChain hybrid retriever response quality by introducing cross-encoder re-ranking with score normalization and relevance threshold filtering, ensuring only the most contextually relevant chunks reach the LLM.

## Requirements

### Requirement: Cross-encoder model selection

The system SHALL use `BAAI/bge-reranker-v2-minicpm-layerwise` as the default cross-encoder re-ranking model.

#### Scenario: Model loads on first use
- **WHEN** the cross-encoder re-ranker is invoked for the first time
- **THEN** the model SHALL be downloaded from HuggingFace Hub and cached locally
- **THEN** subsequent invocations SHALL use the cached model

#### Scenario: Configurable model
- **WHEN** the `reranker_model` setting is changed in configuration
- **THEN** the system SHALL use the specified model on next initialization

### Requirement: Score normalization

The system SHALL normalize cross-encoder scores to the [0, 1] range using min-max normalization before applying the relevance threshold.

#### Scenario: Normalization applied
- **WHEN** the cross-encoder returns raw relevance logits for candidate chunks
- **THEN** the system SHALL compute `normalized = (score - min) / (max - min)` across the candidate set
- **THEN** the normalized scores SHALL be used for threshold filtering

#### Scenario: All scores identical (edge case)
- **WHEN** all cross-encoder scores for the candidate set are equal
- **THEN** the system SHALL skip normalization and retain the original scores
- **THEN** the system SHALL still apply the relevance threshold

### Requirement: Relevance threshold filtering

The system SHALL filter retrieved chunks by `min_relevance_score >= 0.15` using normalized scores.

#### Scenario: Chunks pass threshold
- **WHEN** a chunk's normalized score is >= 0.15
- **THEN** the chunk SHALL be retained for the next pipeline stage

#### Scenario: Chunks fail threshold
- **WHEN** no chunks have a normalized score >= 0.15
- **THEN** the system SHALL return an empty result set
- **THEN** the system SHALL log a warning

### Requirement: Backward compatible API

The system SHALL use `FAISS.from_embeddings()` to build the vector store with pre-computed database embeddings. The embedding function SHALL conform to LangChain's `Embeddings` interface.

#### Scenario: Existing callers unaffected
- **WHEN** `LangChainRetriever.retrieve()` is called
- **THEN** the return type and signature SHALL be identical to before the change
- **THEN** only the internal scoring and filtering SHALL differ

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
