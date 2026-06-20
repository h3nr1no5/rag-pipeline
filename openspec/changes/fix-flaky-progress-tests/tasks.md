## 1. Patch flaky tests

- [x] 1.1 Add `@patch("src.domain.services.processor.trigger_document_processing", lambda doc_id: None)` decorator to `test_status_endpoint_pending_doc_has_zero_saved_chunks`
- [x] 1.2 Add `@patch("src.domain.services.processor.trigger_document_processing", lambda doc_id: None)` decorator to `test_list_endpoint_returns_progress_fields`

## 2. Verify

- [x] 2.1 Run the patched tests 10x each to confirm determinism
- [x] 2.2 Run the full `test_documents_progress.py` suite to confirm no regressions
- [x] 2.3 Run the broader document integration test suite to confirm no regressions
