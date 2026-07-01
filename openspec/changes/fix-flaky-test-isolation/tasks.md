## Phase 1 — Robust DB teardown

- [ ] 1.1 In `tests/conftest.py`, add `import gc` at the top
- [ ] 1.2 In `setup_test_db` teardown, replace `await asyncio.sleep(0.05)` + `_remove_sqlite_file(db_path)` with:
  ```python
  gc.collect()
  for attempt in range(10):
      try:
          _remove_sqlite_file(db_path)
          break
      except PermissionError:
          if attempt == 9:
              raise
          await asyncio.sleep(0.05 * (attempt + 1))
  ```
- [ ] 1.3 Verify by running the batch 3x:
  ```bash
  uv run pytest tests/integration/test_documents.py tests/integration/test_documents_integration.py tests/integration/test_rag_pipelines_e2e.py tests/integration/test_clear_embeddings.py -v --tb=short
  ```
  Expect 0 `readonly database` errors across all 3 runs.

## Phase 2 — Canonical auth_client

- [ ] 2.1 Verify the canonical `auth_client` fixture already exists in `tests/integration/conftest.py` (lines 102-121) — it is correct. No changes needed.

- [ ] 2.2 Delete duplicate `auth_client` from `tests/integration/test_auth_flow.py` (lines 17-38). The file defines its own `client` fixture (lines 10-14) which is fine — only delete the `auth_client` fixture.
  - Analyze: does `test_auth_flow.py` import from conftest? It should get the canonical `auth_client` automatically since `conftest.py` is in the same directory.
  - Verify: tests that need auth should import or reference `auth_client` as a fixture parameter. If any test uses a `client` parameter (non-authenticated), that stays.

- [ ] 2.3 Delete duplicate `auth_client` from `tests/integration/test_documents.py`

- [ ] 2.4 Delete duplicate `auth_client` from `tests/integration/test_documents_integration.py`

- [ ] 2.5 Delete duplicate `auth_client` from `tests/integration/test_query_flow.py`

- [ ] 2.6 Delete duplicate `auth_client` from `tests/integration/test_cache_bug.py`

- [ ] 2.7 Delete duplicate `auth_client` from `tests/integration/test_clear_embeddings.py`

- [ ] 2.8 Delete duplicate `auth_client` from `tests/integration/test_score_normalization.py`

- [ ] 2.9 Verify no remaining duplicates:
  ```bash
  grep -n "async def auth_client" tests/integration/*.py | grep -v conftest.py
  ```
  Expected: empty (0 results — all auth_client definitions are in conftest.py only).

- [ ] 2.10 Verify batch auth tests pass:
  ```bash
  uv run pytest tests/integration/test_auth_flow.py tests/integration/test_documents.py tests/integration/test_documents_integration.py tests/integration/test_query_flow.py tests/integration/test_cache_bug.py tests/integration/test_score_normalization.py -v --tb=short
  ```
  Expect 0 `401 Not Authenticated` errors.

- [ ] 2.11 Run the full integration auth + documents batch 3x to confirm 401 flakiness is eliminated.

## Phase 3 — GC collection safety net

- [ ] 3.1 In `tests/conftest.py`, add autouse fixture that runs `gc.collect()` after every test:
  ```python
  @pytest.fixture(autouse=True)
  def collect_garbage():
      yield
      gc.collect()
  ```
  Place it after the `import gc` (added in 1.1) and before the fixture definitions.

- [ ] 3.2 Verify GC overhead is negligible:
  ```bash
  uv run pytest tests/unit/ -v --tb=short -q 2>&1 | tail -3
  ```
  Time should be approximately the same as before (within 10%).

## Phase 4 — Mark known flaky tests

- [ ] 4.1 Add `@pytest.mark.flaky(reason="readonly database — see fix-flaky-test-isolation")` to:
  - `tests/integration/test_documents.py::test_upload_pdf_document`
  - `tests/integration/test_documents_integration.py::test_upload_python_guide`
  - `tests/integration/test_documents_integration.py::test_document_processing_status_updates`
  - `tests/integration/test_rag_pipelines_e2e.py::test_cosine_pipeline`
  - `tests/integration/test_clear_embeddings.py::test_clear_embeddings_then_reprocess`

- [ ] 4.2 Add `@pytest.mark.flaky(reason="401 auth token — see fix-flaky-test-isolation")` to:
  - `tests/integration/test_documents.py::test_upload_multiple_documents`
  - `tests/integration/test_query_flow.py::test_list_selected_documents`

- [ ] 4.3 Add `@pytest.mark.flaky(reason="state pollution — see fix-flaky-test-isolation")` to:
  - `tests/integration/test_langchain_verification.py::TestLangChainStreaming::test_streaming_success`
  - `tests/integration/test_langchain_verification.py::TestLangChainStreaming::test_streaming_empty_document_ids`

- [ ] 4.4 Add `@pytest.mark.flaky(reason="MPNet segfault — see fix-flaky-test-isolation")` to:
  - `tests/integration/test_documents.py::test_upload_yaml_api_document`

- [ ] 4.5 Verify marker exclusion works:
  ```bash
  uv run pytest -m "flaky" -v --tb=short -q 2>&1 | tail -5
  ```
  Expected: exactly 9 tests collected (the 9 marked).

  ```bash
  uv run pytest -m "not flaky" -v --tb=short -q 2>&1 | tail -3
  ```
  Expected: all other tests run, none of the 9 flaky ones appear.

## Phase 5 — Verification

- [ ] 5.1 Run the known-flaky batch 3 times:
  ```bash
  for i in 1 2 3; do
    echo "=== Run $i ==="
    uv run pytest tests/integration/test_documents.py tests/integration/test_documents_integration.py tests/integration/test_query_flow.py tests/integration/test_rag_pipelines_e2e.py tests/integration/test_clear_embeddings.py tests/integration/test_langchain_verification.py -v --tb=short -q 2>&1 | tail -5
  done
  ```
  Expect 0 failures across all 3 runs.

- [ ] 5.2 Run the full integration suite:
  ```bash
  uv run pytest tests/integration/ -v --tb=short -q 2>&1 | tail -10
  ```
  Expect 0 flaky failures (known skipped tests like `test_link_aware_rag` and `test_llm_loading` are OK).

- [ ] 5.3 Run the full suite (excluding slow):
  ```bash
  uv run pytest -m "not slow" -v --tb=short -q 2>&1 | tail -5
  ```
  Expect expected pass counts.

- [ ] 5.4 Remove `@pytest.mark.flaky` from all tests that passed all 3 verification runs. If any test still flakes, investigate further and either:
  - Leave the `flaky` marker if the root cause is genuinely outside our control
  - Or add a more targeted fix

- [ ] 5.5 Update `AGENTS.md` test commands section if needed.
