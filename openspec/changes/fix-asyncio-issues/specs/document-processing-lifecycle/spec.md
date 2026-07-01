# Document Processing Lifecycle & Reliability — Delta Spec

## MODIFIED Requirements

### Requirement 1: Pending document recovery on startup

The server SHALL scan for documents with `status="pending"` on startup and trigger their processing via `trigger_document_processing(id)`.

(Unchanged — no modification to recovery behavior.)

### Requirement 2: Progress updates during model loading

The processing pipeline SHALL push a progress update to the database before entering any long-running or model-loading phase.

**Modification**: The processing loop SHALL commit chunks to the database in batches of 10 instead of after every individual chunk. The `session.commit()` call inside the chunk-saving loop SHALL be replaced with `session.flush()`, with a full `commit()` only at batch boundaries and on completion.

**Rationale**: Per-chunk commits generate one fsync per chunk (N fsyncs for N chunks). Batching reduces this to N/10 fsyncs, significantly reducing I/O pressure during document processing.

#### Scenario 2b: Batch embedding phase
- **WHEN** the model is loaded and batch encoding begins
- **THEN** the document status SHALL be updated to `step="indexing", message="Embedding N chunks…"`
- **THEN** the `processed_chars` column SHALL update periodically (every 10 chunks or every 2 seconds, whichever comes first)

#### Scenario 2c: Chunks committed in batches
- **WHEN** `process_document_async()` saves chunks to the database
- **THEN** `session.flush()` SHALL be called after each chunk (not `session.commit()`)
- **THEN** `session.commit()` SHALL be called every 10 chunks and after the final chunk
- **AND** stale-task detection SHALL run at the same batch boundaries

### Requirement 5 (ADDED): Eliminate redundant DB sessions in processing loop

The `process_document_async()` function SHALL consolidate its three separate `async_session_maker()` contexts into a single session for the chunk processing phase, reducing session churn.

#### Scenario 5a: total_chars update uses main session
- **WHEN** `process_document_async()` computes `total_chars = len(text)`
- **THEN** the `total_chars` and `processed_chars` updates SHALL use the existing main session (not a new session)
- **AND** SHALL be committed before entering the chunk processing loop

#### Scenario 5b: Final completion status uses main session
- **WHEN** all chunks are saved successfully
- **THEN** the document's `status = "completed"` update SHALL use the existing main session
- **AND** SHALL be committed once after all chunks are saved and batched commits are done
