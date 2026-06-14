## Context

The test suite has evolved organically, accumulating five distinct hygiene issues:

1. **Background task leak**: `src/domain/services/processor.py:448` uses `asyncio.create_task` to fire off document processing. The `setup_test_db` fixture at `tests/conftest.py` swaps `processor.async_session_maker` but never restores it, and the background task is never cancelled during fixture teardown. This means: (a) the background task holds a reference to a stale session maker, and (b) it can outlive the test and fail or corrupt state in subsequent tests.

2. **Upload directory pollution**: `./data/uploads/` accumulates files across tests. The existing `pytest_sessionfinish` hooks clean them at session-end, but per-test isolation is missing — tests can accidentally depend on files left by prior tests.

3. **Duplicate `pytest_sessionfinish` hooks**: 7 test files define their own `pytest_sessionfinish` with near-identical cleanup logic (glob patterns, upload directory cleanup). This is redundant and error-prone: adding a new cleanup pattern requires updating 7+ files.

4. **Redundant `setup_test_db` fixtures**: 6 files define essentially the same fixture — create an engine, swap session makers, create tables, seed defaults, yield, tear down. The only differences are DB file naming prefixes (`test_integration_db_`, `test_chat_db_`, `test_db_`, etc.).

5. **Uvicorn subprocess in tests**: `test_user_persistence.py` spawns real uvicorn processes on hardcoded port 8000 using `subprocess.Popen`. The subprocess restart logic at line 130 calls `Popen` without capturing the handle, creating orphaned zombie processes. Port 8000 conflicts with the dev server. The `test_server_smoke.py` file uses a similar pattern but with dynamic ports and proper cleanup.

Additionally, 4 `auth_client` fixtures have dead `pass` statements as their first line (leftover from development).

## Goals / Non-Goals

**Goals:**
- Eliminate test pollution from background tasks — cancel and await during teardown
- Ensure `./data/uploads/` is cleaned per-test, not just per-session
- Consolidate all `pytest_sessionfinish` hooks into a single location
- Consolidate all `setup_test_db` fixtures into a single shared fixture
- Replace real subprocess server in `test_user_persistence.py` with in-process ASGI transport
- Remove dead `pass` statements from auth_client fixtures
- Ensure tests can run independently and in any order with no cross-test contamination

**Non-Goals:**
- Rewriting or refactoring test logic beyond the hygiene fixes
- Adding new test coverage
- Changing production code behavior
- Re-architecting the test infrastructure (e.g., moving to pytest-xdist, docker containers)

## Decisions

### Decision 1: Background task cancellation in conftest teardown
**Approach**: Add a fixture that cancels all pending `asyncio` tasks created by the processor during teardown, with a short timeout. Track the processor's task references using a set or use `asyncio.all_tasks()` filtering. Restore `processor.async_session_maker` to the original session maker in the teardown phase (it's already done for `db_session` but missing for `processor.async_session_maker` — the fix is to add the restore in the teardown block.

**Alternative considered**: Require all background tasks to complete before teardown. Rejected because some tests don't trigger processing, making it wasteful to wait. Timeout-based cancellation is safer — it bounds the wait and cleans up regardless.

### Decision 2: Per-test upload directory cleanup
**Approach**: Add a `clean_uploads_dir` fixture (autouse, scope=function) that wipes `./data/uploads/` before each test. Use a single location for the upload directory, configurable via settings.

**Alternative considered**: Cleaning after each test. Rejected because cleanup-before is more defensive — a test that crashes can still affect the next run if cleanup is after. Using cleanup-before ensures a clean slate regardless of prior test state.

### Decision 3: Single `pytest_sessionfinish` in root conftest
**Approach**: Remove all `pytest_sessionfinish` hooks from individual test files. Keep the one in `tests/conftest.py` which is the root conftest. Move any file-specific cleanup patterns (e.g., `test_chat_db_*.sqlite`) into the root conftest's glob patterns so no cleanup knowledge is lost.

**Alternative considered**: Using a shared hook via pytest plugin. Overkill — the root conftest's hook already runs first (`tryfirst=True`) and consolidating patterns there is simple enough.

### Decision 4: Single `setup_test_db` in root conftest, parameterized if needed
**Approach**: Remove all `setup_test_db` definitions from individual test files. The root conftest's `setup_test_db` fixture is already `autouse=True` and `scope="function"`, so it already applies to all tests. It needs three fixes:
- Also restore `processor.async_session_maker` in teardown (currently missing)
- Add `clean_uploads_dir` logic
- Ensure the DB file naming is consistent (use a single prefix like `test_db_`)

**Alternative considered**: Parameterized fixture per directory. Unnecessary — the root conftest fixture already runs for all tests automatically.

### Decision 5: Replace uvicorn subprocess with ASGI transport
**Approach**: Rewrite `test_user_persistence.py` to use `httpx.AsyncClient` with `ASGITransport(app=app)` like every other integration test, instead of `subprocess.Popen(["uvicorn", ...])`. Use the shared `setup_test_db` fixture for database isolation and `auth_client` for authentication. The "restart" test scenario can be handled by creating two separate test functions or using a new `AsyncClient` per call — no subprocess needed.

**Alternative considered**: Keep subprocess but use dynamic ports and PID tracking. Rejected because: (a) it's slower, (b) it creates external dependencies (port binding, subprocess lifecycle), and (c) the ASGI transport pattern is already established and proven in the suite. The "restart" test purpose is to verify user persistence across server restarts, which can be adequately tested by creating and re-querying users within the same process.

### Decision 6: Fix dead `pass` statements
**Approach**: Remove the spurious `pass` line from `test_documents_integration.py:14`, `test_documents.py:11`, `test_strategies.py:10`, and `test_query_flow.py:11`. These are leftover stubs that don't affect behavior but are dead code.

## Risks / Trade-offs

- **[Risk] Background task cancellation may mask bugs**: If a test relies on a background task completing, cancellation could cause silent data loss. **Mitigation**: Tasks are only cancelled during teardown — test assertions must verify state before teardown. Document that async processing tests should `await` the processing task explicitly.
- **[Risk] ASGI transport behaves differently from real uvicorn**: The in-process transport doesn't test WSGI middleware, signal handling, or process-level isolation. **Mitigation**: This test was testing auth persistence, not server features. The ASGI transport provides the same application-level behavior. The existing `test_server_smoke.py` already covers the real server startup case.
- **[Risk] Cleanup-before could delete files a test just created**: The next test's cleanup could delete files created by the previous test. **Mitigation**: This is the desired behavior — each test starts fresh. The cleanup-before ensures a test that writes to uploads doesn't leave garbage.
- **[Risk] Consolidating hooks may miss file-specific patterns**: Removing hooks from individual files might lose cleanup patterns. **Mitigation**: Audit all 7 removed hooks for unique glob patterns and migrate them to the root conftest.
