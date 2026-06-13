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

The hybrid retrieval interface (`retrieve(question, top_k) -> list[RetrievedChunkResult]`) SHALL remain unchanged.

#### Scenario: Existing callers unaffected
- **WHEN** `LangChainRetriever.retrieve()` is called
- **THEN** the return type and signature SHALL be identical to before the change
- **THEN** only the internal scoring and filtering SHALL differ
