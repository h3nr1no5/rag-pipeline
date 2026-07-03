## 1. Enable WAL mode in SQLite engine

- [x] 1.1 Add `@event.listens_for(engine.sync_engine, "connect")` to set `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=60000` in `src/infrastructure/database/session.py`

## 2. Add session parameter to helper functions

- [x] 2.1 Add optional `session: AsyncSession | None = None` parameter to `update_document_progress()` in `processor.py`
- [x] 2.2 Implement passed-session path in `update_document_progress()` — use `session` directly with `flush()` when provided, own session with `commit()` when None
- [x] 2.3 Add optional `session: AsyncSession | None = None` parameter to `mark_document_failed()` in `processor.py`
- [x] 2.4 Implement passed-session path in `mark_document_failed()` — use `session` directly with `begin_nested()` + `commit()` when provided, own session when None
- [x] 2.5 Add optional `session: AsyncSession | None = None` parameter to `_persist_api_doc_index()` in `api_doc_processor.py`
- [x] 2.6 Implement passed-session path in `_persist_api_doc_index()` — use `session` directly with `flush()` when provided, own session when None

## 3. Update call sites in process_document_async

- [x] 3.1 Pass `session` to `update_document_progress` at all 9 call sites (lines 144, 167, 218, 234, 286, 388, 442, 476, 551)
- [x] 3.2 Pass `session` to `mark_document_failed` at all 7 call sites inside session (lines 141, 154, 157, 250, 322, 452, 473)
- [x] 3.3 Replace inline `err_session` (line 306) to use main `session` with `begin_nested()` + `commit()`
- [x] 3.4 Pass `session` to `_persist_api_doc_index` call at line 257
- [x] 3.5 Thread `session` through `_ApiDocProgressReporter` — capture in constructor, pass to `update_document_progress` in `report()`

## 4. Verify remaining call sites (outside session) unchanged

- [x] 4.1 Confirm `mark_document_failed` at lines 589, 595, 599 still use own session (outside the `async with session:` block)

## 5. Run tests

- [x] 5.1 Run `uv run pytest tests/ -q` to verify no regressions
- [x] 5.2 Run `uv run mypy src/` to verify type correctness
