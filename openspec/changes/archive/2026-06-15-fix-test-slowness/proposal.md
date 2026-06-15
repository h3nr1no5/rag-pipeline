## Why

The test suite takes ~10 minutes to run 775 tests. A waste audit identified ~700s of avoidable overhead from three dominant sources: (1) autouse fixtures in the root conftest run for all 667 tests that don't need them (~240s), (2) sleep-based 1s polling in 7 copy-pasted `upload_and_wait_for_document` helpers with unnecessary settling sleeps (~190s), and (3) per-chunk DB commits and per-chunk embedding in `processor.py` that inflate document processing time (~100s). Additional waste comes from real LLM model loading, real uvicorn subprocess spawning, MonitoringMiddleware logging noise, and scattered standalone sleeps. Fixing these will cut runtime to ~2-3 minutes while preserving test correctness.

## What Changes

1. **Override root autouse fixtures in `tests/unit/` and `tests/pdf_semantic_chunking/`** — Create `tests/unit/conftest.py` and edit `tests/pdf_semantic_chunking/conftest.py` to override `setup_test_db`, `clean_uploads_dir`, and `cancel_background_tasks` as no-ops. Pytest fixture resolution picks the most specific conftest, so the root autouse fixtures are silently skipped for these test directories.
2. **Extract shared `wait_for_document` helper** — Create `tests/integration/conftest.py` with a reusable `wait_for_document()` function using 0.1s polling, no settling sleep, configurable timeout, and `time.monotonic()`. Replace all 7 copy-pasted implementations across integration test files.
3. **Centralize `auth_client` fixture** — Add a shared `auth_client` fixture to `tests/integration/conftest.py`. Remove 16 nearly identical local definitions from individual test files.
4. **Batch DB commits in `processor.py`** — Remove `await session.commit()` from inside the per-chunk loop (lines 383 and 402) in both the semantic and regular chunking paths. Keep the post-loop commit that flushes all changes in one transaction. Keep progress-update commits for UI purposes during long runs.
5. **Batch embedding in `processor.py`** — Replace per-chunk `embedder.embed_text()` calls with a single `embedder.embed_texts()` call that processes all chunks at once, leveraging sentence-transformers batch encoding.
6. **Guard `test_llm_loading.py` with env var** — Add `@pytest.mark.skipif` gated on `RUN_LLM_TESTS` environment variable. Only runs when explicitly requested.
7. **Convert `test_server_smoke.py` to ASGITransport** — Replace real uvicorn subprocess with `httpx.AsyncClient(transport=ASGITransport(app=app))`, matching the pattern used by all other integration tests.
8. **Disable MonitoringMiddleware during tests** — Skip middleware registration when `TESTING=1` environment variable is set.
9. **Remove standalone `asyncio.sleep(2)` calls** — Delete 6 scattered `sleep(2)` calls that are compensating for slow polling (made unnecessary by fixes 4 and 5).
10. **Lazy-load heavy imports in test files** — Move `import fitz` and `import docx` to function level to avoid loading PyMuPDF/python-docx for all tests in a file when only some need them.
11. **Remove duplicate `atexit` cleanup** — Delete `atexit.register(_cleanup_test_artifacts)` from `tests/conftest.py`; `pytest_sessionfinish` already handles cleanup reliably.

## Capabilities

### New Capabilities

- `test-performance`: Test-side performance optimizations including conftest overrides for unit/pdf_semantic_chunking tests, shared wait_for_document helper, centralized auth_client fixture, MonitoringMiddleware suppression, standalone sleep removal, LLM test guard, lazy import loading, duplicate cleanup removal, and server smoke test conversion to ASGITransport.

- `processor-batch-operations`: Batch DB commit consolidation and batch embedding in `src/domain/services/processor.py` to reduce per-document processing time by eliminating redundant transaction and model-inference overhead.

### Modified Capabilities

- `test-isolation`: Update requirements to allow per-directory conftest overrides of autouse fixtures. The autouse fixtures (`setup_test_db`, `clean_uploads_dir`, `cancel_background_tasks`) remain the default for the root test directory, but subdirectories (`tests/unit/`, `tests/pdf_semantic_chunking/`) MAY override them as no-ops when their tests don't require database access, upload directory interaction, or background task management.

- `test-infra-consolidation`: Extend requirements to include consolidation of the `upload_and_wait_for_document` helper pattern and centralized `auth_client` fixture. The shared `wait_for_document()` function SHALL replace all 7 copy-pasted implementations. The shared `auth_client` fixture SHALL replace all 16 local definitions.

## Impact

- **Modified files**: `tests/conftest.py`, `tests/unit/conftest.py` (new), `tests/pdf_semantic_chunking/conftest.py`, `tests/integration/conftest.py` (new), `src/domain/services/processor.py`, `src/api/main.py`
- **Modified test files**: `tests/integration/test_rag_comparison.py`, `tests/integration/test_pdf_integration.py`, `tests/integration/test_chat_integration.py`, `tests/integration/test_clear_embeddings.py`, `tests/integration/test_cache_bug.py`, `tests/integration/test_chat_e2e.py`, `tests/integration/test_documents_integration.py`, `tests/integration/test_server_smoke.py`, `tests/integration/test_llm_loading.py`, `tests/integration/test_link_aware_rag.py`
- **Dependencies**: None new. Removes `atexit` as a module-level import from root conftest.
- **Risk profile**: Low. All changes are mechanical optimizations that preserve existing behavior. The most risky change (processor.py commit batching) affects timing but not correctness — if a crash occurs mid-loop, partial chunk loss is the same as current behavior.
