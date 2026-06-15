## Purpose

Standardize embedding normalization and score scaling across all RAG backends to ensure consistent similarity scoring and configurable relevance thresholds.

## Requirements

### Requirement: Embeddings shall be normalized at storage time
The document processor SHALL L2-normalize all embedding vectors before writing them to the database. All backends SHALL compute similarity as dot-product on these normalized vectors, which equals true cosine similarity.

#### Scenario: Processor normalizes embeddings on chunk creation
- **WHEN** `processor.py` creates a new chunk and stores its embedding
- **THEN** the stored embedding SHALL have unit L2 norm (within floating-point tolerance of 1.0)

#### Scenario: All backends produce consistent scores
- **WHEN** the same query and document are searched via the cosine, LangChain, and LlamaIndex backends
- **THEN** the similarity scores for the same chunk SHALL be within 0.01 of each other across backends (accounting for different retrieval algorithms)

### Requirement: Score normalization for retrieval results
All retrieval backends SHALL apply min-max normalization to scores before returning them, producing a [0, 1] range. The `min_relevance_score` threshold SHALL be applied after normalization.

#### Scenario: Cosine backend returns normalized scores
- **WHEN** the cosine backend retrieves chunks
- **THEN** each returned chunk SHALL have a score in [0, 1] range

#### Scenario: LangChain backend retains existing normalization
- **WHEN** the LangChain backend retrieves chunks
- **THEN** the existing min-max normalization SHALL continue to produce [0, 1] scores (no regression)

#### Scenario: LlamaIndex backend applies min-max normalization
- **WHEN** the LlamaIndex backend retrieves chunks
- **THEN** each returned chunk SHALL have a score in [0, 1] range

### Requirement: Hardcoded thresholds replaced with configurable setting
All backends SHALL use the shared `min_relevance_score` setting from `src/core/config.py` instead of hardcoded values.

#### Scenario: LlamaIndex uses configurable min_relevance_score
- **WHEN** the LlamaIndex backend filters retrieved chunks
- **THEN** it SHALL use `settings.min_relevance_score` instead of a hardcoded threshold

#### Scenario: Threshold applies after score normalization
- **WHEN** filtering chunks by relevance
- **THEN** the threshold SHALL be applied after min-max score normalization is complete
