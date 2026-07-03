## Context

Document processing (`process_document_async` in `processor.py`) opens a main SQLAlchemy async session that holds uncommitted writes via `flush()` throughout the processing pipeline. Four helper functions — `update_document_progress()`, `mark_document_failed()`, an inline `err_session` block, and `_persist_api_doc_index()` — each open their own **separate** session via `async_session_maker()`. SQLite's default exclusive locking mode blocks concurrent writes, causing these nested sessions to fail with `"database is locked"`. Progress updates are silently lost (WARNING logged, no retry), and error statuses fail to persist.

**Affected files:**
- `src/domain/services/processor.py` — `update_document_progress` (line 38), `mark_document_failed` (line 67), inline `err_session` (line 306)
- `src/domain/services/api_doc_processor.py` — `_persist_api_doc_index` (line 112)
- `src/infrastructure/database/session.py` — engine creation (WAL mode)

## Goals / Non-Goals

**Goals:**
- Eliminate all nested `async_session_maker()` calls during document processing
- Ensure progress updates, error statuses, and persistence writes use the main session
- Apply correct `flush()` vs `commit()` discipline per call site
- Add WAL mode as defense-in-depth against concurrent write contention
- Maintain backward compatibility for callers outside `process_document_async`

**Non-Goals:**
- No changes to API endpoints, DB schema, or models
- No retry logic for `update_document_progress` failures (with fix, they won't occur)
- No changes to the chunking or embedding logic

## Decisions

### Decision 1: Optional session parameter (not mandatory)

**Choice:** Add `session: AsyncSession | None = None` to all four functions.

**Rationale:**
- **Backward compatible** — existing callers outside `process_document_async` (e.g., startup recovery in `main.py`) work unchanged
- **Minimal diff** — each call site within `process_document_async` adds only `session=session`
- **Standard SQLAlchemy pattern** — passing a session through a call chain is idiomatic

**Alternatives considered:**
- **Context variable** (`contextvars`) — more complex, harder to test, unclear lifecycle
- **Mandatory session parameter** — would break all external callers
- **Inline all progress updates** — reduces readability, duplicates SELECT logic

### Decision 2: `flush()` vs `commit()` differentiation

**Choice:**
- `update_document_progress` → `flush()` (non-terminal, caller controls batch commits)
- `_persist_api_doc_index` → `flush()` (non-terminal, caller commits at line 269)
- `mark_document_failed` → `commit()` (terminal, always followed by `return`)
- `err_session` block → `commit()` (terminal, always followed by `return`)

**Rationale:**
The critical insight from review: if `mark_document_failed` calls only `flush()` and then `return` exits the `async with session:` context, the transaction **rolls back**, losing the "failed" status entirely. All 7 call sites of `mark_document_failed` inside the main session are terminal (followed by `return`), so committing is always correct. Same for the inline `err_session`.

### Decision 3: Savepoints for error handlers

**Choice:** Wrap `mark_document_failed` and `err_session` writes in `begin_nested()` (savepoint) when using a passed session.

**Rationale:** If the main session is in a broken state (e.g., from a failed chunk INSERT), direct writes would also fail. A savepoint isolates the error-marking write into a nested transaction — if it fails, only the savepoint rolls back, not the outer session. Combined with `commit()`, this persists the "failed" status.

### Decision 4: WAL mode engine-wide

**Choice:** Add `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=60000` to the SQLite engine via SQLAlchemy's `@event.listens_for(engine.sync_engine, "connect")`.

**Rationale:** Defense-in-depth. Even with the shared-session fix, WAL mode ensures:
- Concurrent readers never block writers (e.g., user polls document status while processing runs)
- Mitigates edge cases where `mark_document_failed` at lines 589/595/599 (outside the main session) writes while another session holds a lock
- `busy_timeout` prevents immediate failure if a lock is briefly contended

### Decision 5: `_ApiDocProgressReporter` captures session

**Choice:** Pass `session` to `_ApiDocProgressReporter` constructor and forward it to `update_document_progress`.

**Rationale:** The reporter is used as a callback inside `_process_api_doc`, which doesn't have access to the main session. The session must be captured at construction time (inside `process_document_async`) and passed through each `report()` call.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **Broken session in error handler** — if `mark_document_failed` is called after a DB error that left the session broken, the write fails too | Savepoints (`begin_nested()`) isolate the write; if it fails, the error is logged and the function exits gracefully |
| **Data loss on mid-processing crash** — partially committed chunks remain in DB if processing crashes after a batch commit but before completion | Existing behavior unchanged; WAL mode does not affect this |
| **Performance of WAL mode** — slightly larger DB file, slightly slower writes (WAL overhead) | Negligible for this workload; WAL is the recommended mode for SQLite + concurrent access |
| **Forgotten call sites** — a developer adds a new `update_document_progress` call without passing `session` | The fallback path (own session) still works; it's just suboptimal. WAL mode reduces the impact of such mistakes |
| **Session staleness** — using the passed session after a batch `commit()` might show stale `current_processing_config_id` | The inline staleness check at lines 396-408 / 559-571 re-fetches the Document after commit, which is correct |
