## Purpose

TBD — LlamaIndex-based retrieval backend for the RAG pipeline.

## Requirements

### Requirement: Backend validates chunk embeddings before dense retrieval

The LlamaIndex retriever SHALL validate every chunk's stored embedding before computing dense similarity scores. Validation SHALL reject embeddings that are:

- `None` / null
- Not a list or tuple type
- A different length than the query embedding (dimension mismatch)
- Containing NaN values
- Containing Inf or -Inf values

Chunks with invalid embeddings SHALL receive a score of 0.0 and SHALL be excluded from dense retrieval top-k selection.

#### Scenario: Null embedding is handled gracefully
- **WHEN** a chunk in the database has a `NULL` embedding
- **THEN** the chunk receives score 0.0 and is not selected among the dense top-k results

#### Scenario: Dimension mismatch is detected
- **WHEN** a chunk's embedding has a different length than the query embedding
- **THEN** the chunk receives score 0.0 and a warning is logged

#### Scenario: NaN embedding is detected
- **WHEN** a chunk's embedding contains NaN values
- **THEN** the chunk receives score 0.0 and a warning is logged

#### Scenario: Inf embedding is detected
- **WHEN** a chunk's embedding contains Inf or -Inf values
- **THEN** the chunk receives score 0.0 and a warning is logged

### Requirement: SQL query filters out NULL embeddings

The `_ensure_components()` method SHALL include `Chunk.embedding.isnot(None)` in its SQL query to exclude chunks without embeddings before loading.

#### Scenario: NULL embeddings are not loaded
- **WHEN** the retriever loads chunks from SQLite
- **THEN** the WHERE clause includes `chunk.embedding IS NOT NULL`

### Requirement: Score normalization handles degenerate cases

When all retrieved nodes have identical scores (or only one node is retrieved), the min-max normalization `(score - min) / (max - min)` SHALL NOT skip the score assignment. Instead, the top node SHALL receive a score of 1.0 to ensure it passes the `min_relevance_score` threshold.

#### Scenario: Single node result has score 1.0 after normalization
- **WHEN** only one node survives RRF fusion (dense and BM25 both point to the same chunk)
- **THEN** the node SHALL have score 1.0

#### Scenario: Identical scores produce one top-scoring result
- **WHEN** all nodes have scores within 1e-10 of each other
- **THEN** the top-ranked node SHALL receive score 1.0

### Requirement: Backend emits stage-level debug logging

The LlamaIndex retriever SHALL emit `logger.debug()` messages at each retrieval stage:

1. Number of chunks loaded from SQLite
2. Number of chunks with valid vs. invalid embeddings
3. Dense retrieval top-k scores (min, max, mean)
4. BM25 results count
5. RRF result count and scores
6. Cross-encoder success or fallback
7. Normalized scores (min, max, mean)
8. Number of results before and after `min_relevance_score` filtering

#### Scenario: DEBUG logging is emitted for each stage
- **WHEN** a retrieval is performed with `LOG_LEVEL=DEBUG`
- **THEN** all eight stage logs are emitted at DEBUG level

#### Scenario: WARNING is logged for filtered results
- **WHEN** all results are filtered by `min_relevance_score`
- **THEN** a WARNING-level log is emitted with the count of eliminated nodes

### Requirement: Integration tests verify end-to-end behavior

The project SHALL include integration tests for the LlamaIndex backend that:

- Test both streaming (`/api/v1/query/llamaindex/stream`) and non-streaming (`/api/v1/query/llamaindex`) endpoints
- Verify retrieval returns sources with valid scores when chunks have embeddings
- Verify the "I don't have enough information" message when no chunks pass the relevance threshold
- Verify that NULL embeddings produce logged warnings and do not crash

#### Scenario: Non-streaming LlamaIndex query returns sources
- **WHEN** a non-streaming query is made with valid documents
- **THEN** the response includes sources with non-empty content and scores

#### Scenario: Streaming LlamaIndex query returns tokens
- **WHEN** a streaming query is made with valid documents
- **THEN** the SSE stream yields sources followed by tokens

#### Scenario: No relevant chunks returns informational message
- **WHEN** no chunks pass `min_relevance_score`
- **THEN** the response is "I don't have enough information to answer this question." with empty sources

### Requirement: Embedding validation is a shared utility

The embedding validation logic SHALL be extracted from `_retrieval.py` into a shared function in `embedding.py` so that both the cosine and LlamaIndex backends use the same validation code.

#### Scenario: Cosine backend uses shared validation
- **WHEN** `_retrieval.py` validates embeddings
- **THEN** it calls the shared `validate_embedding()` function

#### Scenario: LlamaIndex backend uses shared validation
- **WHEN** `retrieval_llamaindex.py` validates embeddings
- **THEN** it calls the shared `validate_embedding()` function
