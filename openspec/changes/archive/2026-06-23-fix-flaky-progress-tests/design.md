## Context

The `test_documents_progress.py` file contains 5 integration tests that verify document processing progress fields. Two of these tests (`test_list_endpoint_returns_progress_fields` and `test_status_endpoint_pending_doc_has_zero_saved_chunks`) assert `saved_chunks == 0` immediately after uploading a document. The upload endpoint (`POST /api/v1/documents`) fires an async background task via `trigger_document_processing` that can increment `saved_chunks` concurrently. This creates a race condition where the background task's save loop writes `saved_chunks = i + 1` before the test reads it.

The pattern was already fixed for `test_reprocess_resets_saved_chunks` in a prior change using `@patch` to mock the background task trigger to a no-op.

## Goals / Non-Goals

**Goals:**
- Make `test_list_endpoint_returns_progress_fields` fully deterministic (confirmed flaky: 1/10 failures)
- Make `test_status_endpoint_pending_doc_has_zero_saved_chunks` deterministic (same logical vulnerability, narrower race window)
- Keep the fix minimal and consistent with the existing patch pattern in the same file

**Non-Goals:**
- Do not modify any production code (the processor already has stale-task detection via config ID comparison)
- Do not address the 14+ polling-loop tests (they are safe but slow — separate optimization)
- Do not modify any test files outside `test_documents_progress.py`

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Mock target** | `src.domain.services.processor.trigger_document_processing` | The function is lazily imported inside endpoint handlers, so the patch must target the module where `trigger_document_processing` is *defined*, not where it's *used*. |
| **Mock value** | `lambda doc_id: None` (no-op) | Simpler than `AsyncMock` — the endpoint calls it fire-and-forget and never awaits it. A synchronous no-op is correct. |
| **Patch mechanism** | `@patch` decorator (not context manager) | Consistent with the existing fix for `test_reprocess_resets_saved_chunks`. Keeps patch scope limited to the test function. |
| **Test isolation safety** | No cross-test contamination risk | The `cancel_background_tasks` autouse fixture in conftest.py cleans up any remaining tasks between tests. |

## Risks / Trade-offs

- **[Low] Mock hides real behavior**: Patching `trigger_document_processing` means we're not testing that the background task *would* be triggered. The upload endpoint behavior is still validated (status 201, document created in DB). The background processing path is covered by the polling-loop integration tests.
- **[Low] Missed import after refactor**: If `trigger_document_processing` is moved to a different module, the patch target string becomes stale. Mitigation: tests will fail immediately (import error) with a clear stack trace, making detection trivial.
