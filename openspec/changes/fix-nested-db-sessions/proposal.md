## Why

Document processing gets stuck in "processing" state because `update_document_progress()` and `mark_document_failed()` each open their own SQLite session via `async_session_maker()`, while the caller (`process_document_async`) already holds an open session with uncommitted writes. SQLite's exclusive locking mode blocks the second session's writes with "database is locked". This prevents progress updates from persisting and can leave documents stuck in a half-processed state indefinitely.

## What Changes

1. **Share the main session** — Refactor `update_document_progress()`, `mark_document_failed()`, `err_session` (inline), and `_persist_api_doc_index()` to accept an optional `session` parameter. When called from within `process_document_async`, pass the main session; when called from elsewhere, create a new session as before.
2. **`flush()` vs `commit()` discipline** — `update_document_progress` and `_persist_api_doc_index` use `flush()` (non-terminal, caller controls commits); `mark_document_failed` and `err_session` use `commit()` (always terminal, "failed" status must persist).
3. **Progress reporter threading** — `_ApiDocProgressReporter` captures and passes the main session to `update_document_progress`.
4. **WAL mode** (defense-in-depth) — Enable SQLite WAL mode engine-wide so concurrent readers never block writers in edge cases.

## Capabilities

### New Capabilities

- `shared-session-progress`: Shared SQLAlchemy session for progress/error updates during document processing, eliminating nested `async_session_maker()` calls.

### Modified Capabilities

<!-- No existing specs to modify. This is a bug fix in existing implementation code. -->

## Impact

- **Files modified**: `src/domain/services/processor.py`, `src/domain/services/api_doc_processor.py`, `src/infrastructure/database/session.py`
- **No API changes**: All endpoint signatures remain identical. No new routes, no new models.
- **No DB schema changes**: Existing tables and columns unchanged.
- **No dependency changes**: No new packages required.
