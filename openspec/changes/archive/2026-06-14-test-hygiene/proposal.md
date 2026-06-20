## Why

The test suite has accumulated several hygiene issues that cause flaky tests, performance degradation, zombie processes, and wasted developer time. 22 stale SQLite database files accumulated in `data/`, background tasks leak across test boundaries, fixture setup is duplicated across 7+ files, and one test spawns a real uvicorn subprocess that can orphan. These issues erode trust in the test suite and slow down development.

## What Changes

- **Background task isolation**: Ensure `asyncio.create_task` background processing in the document processor is properly cancelled and joined during fixture teardown, and that `processor.async_session_maker` is restored after each test.
- **Upload directory cleanup**: Ensure uploaded files in `./data/uploads/` are cleaned between tests (not just at session-end), so tests don't accidentally depend on files left by previous runs.
- **Deduplicate `pytest_sessionfinish` hooks**: Remove 7 duplicate session-finish hooks scattered across test files and consolidate into a single session-scoped fixture or conftest hook.
- **Consolidate `setup_test_db` fixtures**: Replace 6 redundant fixture implementations with a single shared fixture in conftest, using a consistent DB file naming scheme.
- **Remove uvicorn subprocess from tests**: Replace the real uvicorn subprocess in `test_user_persistence.py` with an in-process ASGI transport test (consistent with the rest of the suite).

## Capabilities

### New Capabilities
- `test-isolation`: Per-test isolation guarantees — background tasks are cleaned up, uploaded files are wiped, and databases are unique per test.
- `test-infra-consolidation`: Consolidated test infrastructure — single `setup_test_db` fixture, single `pytest_sessionfinish` hook, no subprocess server.

### Modified Capabilities
<!-- No existing specs are modified — this is entirely new test infrastructure. -->

## Impact

- **Files**: `conftest.py`, `tests/conftest.py`, `tests/unit/conftest.py`, `tests/integration/conftest.py`, all individual test files with duplicate hooks/fixtures, `test_user_persistence.py`
- **Dependencies**: No new dependencies
- **Risk**: Low — all changes are in test code only, no production logic touched
- **Performance**: Faster test execution (no subprocess spawn, no 22-stale-db cleanup overhead)
