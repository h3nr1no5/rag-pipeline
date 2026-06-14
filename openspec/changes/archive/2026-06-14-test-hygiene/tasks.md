## 1. Consolidate Test Infrastructure

- [x] 1.1 Remove all 7 duplicate `pytest_sessionfinish` hooks from individual test files (test_chat_integration.py, test_clear_embeddings.py, test_chat_e2e.py, test_cache_bug.py, test_rag_comparison.py, test_pdf_integration.py, test_llm_loading.py) and ensure all cleanup patterns are merged into the root conftest hook
- [x] 1.2 Remove all 5 duplicate `setup_test_db` fixtures from individual test files (test_chat_integration.py, test_cache_bug.py, test_rag_comparison.py, test_pdf_integration.py, test_llm_loading.py) — the root conftest fixture already covers them
- [x] 1.3 Update the root `tests/conftest.py` `setup_test_db` fixture to also restore `processor.async_session_maker` in the teardown phase (currently only restores `db_session.engine`)

## 2. Fix Background Task Leak

- [x] 2.1 Add a `pytest_runtest_teardown` hook or autouse fixture in root conftest that cancels and joins any pending `asyncio` tasks created by the processor with a 5-second timeout
- [x] 2.2 Verify the fix by running tests that trigger document processing (e.g., test_documents_integration.py) and confirming no stale tasks remain after teardown

## 3. Add Per-Test Upload Directory Cleanup

- [x] 3.1 Add an autouse `clean_uploads_dir` fixture (scope=function) in root conftest that removes all files from `./data/uploads/` before each test
- [x] 3.2 Ensure the cleanup gracefully handles a non-existent upload directory

## 4. Rewrite test_user_persistence.py to Use ASGI Transport

- [x] 4.1 Rewrite `test_user_persistence.py` to use `httpx.AsyncClient` with `ASGITransport(app=app)` instead of uvicorn subprocess
- [x] 4.2 Remove all `subprocess.Popen` calls and signal handling logic
- [x] 4.3 Adapt the "login after restart" test scenario to work in-process (e.g., create a fresh client and verify credentials persist)

## 5. Remove Dead Code from auth_client Fixtures

- [x] 5.1 Remove the dead `pass` statement from `test_documents_integration.py:14`
- [x] 5.2 Remove the dead `pass` statement from `test_documents.py:11`
- [x] 5.3 Remove the dead `pass` statement from `test_strategies.py:10`
- [x] 5.4 Remove the dead `pass` statement from `test_query_flow.py:11`

## 6. Clean Up Stale Artifacts and Verify

- [x] 6.1 Remove all stale `.sqlite` files from `./data/` and all files from `./data/uploads/`
- [x] 6.2 Run the full test suite (`uv run pytest -v`) and confirm all tests pass
- [x] 6.3 Run the full test suite a second time to confirm no cross-test pollution
- [x] 6.4 Verify no `.sqlite` files remain in `./data/` after the test session completes
