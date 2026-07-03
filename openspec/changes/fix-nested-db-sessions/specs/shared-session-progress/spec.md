## ADDED Requirements

### Requirement: Document processing progress updates use the same DB session

When `process_document_async` holds an open SQLAlchemy session with uncommitted writes, all progress and error updates (`update_document_progress`, `mark_document_failed`, `_persist_api_doc_index`) SHALL use the same session rather than opening a new one.

#### Scenario: Progress update succeeds during active processing
- **WHEN** `process_document_async` has an open session with uncommitted chunk INSERTs
- **THEN** `update_document_progress` SHALL write the progress update to the same session without a "database is locked" error

#### Scenario: Error marking persists when processing fails
- **WHEN** document processing fails and the main session is still open
- **THEN** `mark_document_failed` SHALL commit the "failed" status to the database before `process_document_async` exits

#### Scenario: WAL mode enables concurrent readers during writes
- **WHEN** a document is being processed (write transaction open)
- **THEN** HTTP GET requests to read document status SHALL NOT be blocked by the write lock

#### Scenario: Backward compatibility for external callers
- **WHEN** `update_document_progress` or `mark_document_failed` is called without a session parameter
- **THEN** the functions SHALL create their own session as before
