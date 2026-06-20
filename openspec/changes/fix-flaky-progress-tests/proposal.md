## Why

Two tests in `test_documents_progress.py` are flaky due to a race condition: uploading a document fires an async background task (`trigger_document_processing`) that can increment `saved_chunks` before the test asserts it equals 0. One failure mode was already confirmed (1/10 failures for `test_list_endpoint_returns_progress_fields`), and the same logical vulnerability exists in `test_status_endpoint_pending_doc_has_zero_saved_chunks`. Flaky tests reduce CI signal and developer trust.

## What Changes

- Add `@patch("src.domain.services.processor.trigger_document_processing", lambda doc_id: None)` decorator to two tests that assert `saved_chunks == 0` after upload, preventing the background task from racing with the assertion.
- No production code changes needed — the recently-added stale-task detection in the processor already guards real-world race conditions.

## Capabilities

### New Capabilities

- `test-flaky-determinism`: Makes `test_list_endpoint_returns_progress_fields` and `test_status_endpoint_pending_doc_has_zero_saved_chunks` deterministic by preventing background processing tasks from racing with test assertions.

### Modified Capabilities

_(No spec-level behavior changes — this is a test-only quality fix.)_

## Impact

- **Test file only**: `tests/integration/test_documents_progress.py` — two test functions gain a `@patch` decorator.
- **No API, DB, or production code changes**.
- **No new dependencies**.
