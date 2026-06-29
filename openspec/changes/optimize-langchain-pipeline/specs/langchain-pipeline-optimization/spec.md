## ADDED Requirements

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

### Requirement: LangChain query completes within 180s (with best-effort target)
The full LangChain query pipeline SHOULD complete in under 180 seconds (the frontend timeout). The candidate pool reduction from ~66 to ~30 docs is expected to bring processing time from ~317s to ~150-170s, but this is a best-effort target — the cross-encoder remains the bottleneck.

#### Scenario: End-to-end query time improvement
- **WHEN** a LangChain query is executed against a document with ~500 chunks
- **THEN** the total backend processing time SHOULD be under 180 seconds
- **AND** the processing time SHALL be measurably lower than before the candidate pool reduction
