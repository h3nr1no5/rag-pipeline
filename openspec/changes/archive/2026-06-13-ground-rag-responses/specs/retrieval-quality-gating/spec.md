## ADDED Requirements

### Requirement: Proper relevance scoring in retrieve()

The `LangChainRetriever.retrieve()` method SHALL compute actual relevance scores instead of hardcoding `score=1.0`. Scores SHALL be the weighted combination `0.5 × BM25_score + 0.5 × FAISS_score`, using reciprocal rank for each retriever's contribution. This matches the existing logic in `retrieve_with_scores()`.

#### Scenario: Real scores returned

- **WHEN** `retrieve()` is called with a query and document chunks
- **THEN** each returned `RetrievedChunkResult` SHALL have a `score` computed from actual BM25 and FAISS relevance, not hardcoded to `1.0`

### Requirement: Relevance score threshold

The `retrieve()` method SHALL apply a minimum relevance score threshold `MIN_RELEVANCE_SCORE = 0.15` (increased from the current unused `0.1`). Chunks with a combined score below this threshold SHALL be excluded from results. If no chunks meet the threshold, the retriever SHALL return an empty list.

#### Scenario: Low-relevance chunks filtered

- **WHEN** a chunk's combined BM25+FAISS score is below `0.15`
- **THEN** the chunk SHALL NOT be included in the retrieval results
- **WHEN** all chunks score below `0.15`
- **THEN** the retriever SHALL return an empty list, and the API SHALL return "I don't have enough information"

### Requirement: Cross-encoder re-ranking

The system SHALL add a cross-encoder re-ranker after initial BM25+FAISS ensemble retrieval. The re-ranker SHALL operate on `top_k=20` results from the ensemble retriever, compute query-document relevance scores, and return the top `request.top_k` (default 5) results.

#### Scenario: Cross-encoder re-ranks results

- **WHEN** `retrieve()` is called
- **THEN** the top 20 results from BM25+FAISS ensemble SHALL be passed through the cross-encoder re-ranker
- **THEN** the final results SHALL be the top `request.top_k` according to cross-encoder scores

#### Scenario: Re-ranker disabled gracefully

- **WHEN** the cross-encoder model fails to load or `RERANKER_ENABLED` is `False`
- **THEN** the system SHALL fall back to ensemble retrieval without re-ranking and log a warning

### Requirement: Cross-encoder as lazy-loaded singleton

The cross-encoder model SHALL be loaded on first use (lazy singleton), following the same pattern as `MLXLLM` and the embedder. A new config entry `RERANKER_MODEL` SHALL specify the model name, defaulting to `cross-encoder/ms-marco-MiniLM-L-6-v2`. A new config entry `RERANKER_ENABLED` (bool, default `True`) SHALL allow disabling the re-ranker.

#### Scenario: Model loads on first use

- **WHEN** a LangChain query is made and `RERANKER_ENABLED` is `True`
- **THEN** the cross-encoder model SHALL be loaded on first use and cached for subsequent queries
- **WHEN** `RERANKER_ENABLED` is `False`
- **THEN** the system SHALL skip re-ranking entirely

### Requirement: Increased retrieval depth

The LangChain retriever SHALL internally request `top_k=20` from the ensemble retriever before re-ranking, regardless of the user's `request.top_k`. The final returned count SHALL respect `request.top_k`.

#### Scenario: Internal depth greater than returned count

- **WHEN** a user requests `top_k=5`
- **THEN** the ensemble retriever SHALL internally retrieve 20 candidates
- **THEN** the re-ranker SHALL score all 20
- **THEN** the system SHALL return only the top 5
