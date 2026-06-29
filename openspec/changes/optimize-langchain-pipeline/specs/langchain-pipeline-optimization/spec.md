## ADDED Requirements

### Requirement: Use faster cross-encoder model
The system SHALL use `cross-encoder/ms-marco-MiniLM-L-6-v2` as the cross-encoder re-ranker model for the LangChain hybrid retrieval pipeline, replacing `Alibaba-NLP/gte-reranker-modernbert-base`.

#### Scenario: Model name configured via settings
- **WHEN** the LangChain retriever initializes the cross-encoder
- **THEN** the model name SHALL be `cross-encoder/ms-marco-MiniLM-L-6-v2`

#### Scenario: Cross-encoder loads successfully
- **WHEN** a LangChain query is executed and the cross-encoder is loaded for the first time
- **THEN** the model SHALL load via `sentence_transformers.CrossEncoder` within 5 seconds

### Requirement: Reduce candidate pool size for re-ranking
The system SHALL reduce `internal_top_k` from 20 to 10 in the LangChain hybrid retrieval pipeline, reducing the BM25 and FAISS candidate pool from 40 docs each to 20 docs each.

#### Scenario: BM25 retrieves fewer candidates
- **WHEN** a LangChain query is executed
- **THEN** BM25 SHALL retrieve at most 20 candidates (k=20) instead of 40

#### Scenario: FAISS retrieves fewer candidates
- **WHEN** a LangChain query is executed
- **THEN** FAISS SHALL retrieve at most 20 candidates (k=20) instead of 40

#### Scenario: Cross-encoder receives fewer candidates
- **WHEN** the cross-encoder re-ranker is invoked
- **THEN** the combined input candidates SHALL be at most approximately 30 (down from ~66)

### Requirement: Backend timeout for LangChain endpoint
The LangChain query endpoint SHALL enforce an `asyncio.wait_for()` timeout of 160 seconds on the query execution, returning HTTP 500 with a clear error message when exceeded.

#### Scenario: Query exceeds backend timeout
- **WHEN** a LangChain query takes longer than 160 seconds
- **THEN** the backend SHALL raise a `TimeoutError` and return HTTP 500 with `{"detail": "LangChain query timed out after 160s"}`
- **AND** the backend SHALL cancel the in-flight query task to free resources

### Requirement: LangChain query completes within 180s
The full LangChain query pipeline SHALL complete in under 180 seconds (the frontend timeout), reducing from the current ~317 seconds.

#### Scenario: End-to-end query time
- **WHEN** a LangChain query is executed against a document with ~500 chunks
- **THEN** the total backend processing time SHALL be under 180 seconds
