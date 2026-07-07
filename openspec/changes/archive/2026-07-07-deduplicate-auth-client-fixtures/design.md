## Context

The `fix-flaky-test-isolation` change established a single canonical `auth_client` fixture at `tests/integration/conftest.py:102-121` and deleted 6 duplicate definitions from test files. A security review of that change found **17 additional files** with copy-pasted `auth_client` fixtures that inherit the same structural problems:

- **Each defines `async def auth_client(setup_test_db)` using the buggy if/elif pattern** where the login response token may be discarded on the 400 branch (UUID collision during retry).
- **Each shadows the canonical fixture** via pytest's conftest resolution. Tests in the same file use the local definition, not the conftest one.
- **None provide unique behavior** — all 17 duplicates are structurally identical variants of the same pattern. No test file introduces custom auth logic that couldn't use the canonical fixture.

### Current State

- Canonical fixture in `tests/integration/conftest.py`: idempotent signup-then-always-login, guaranteed token capture
- 17 duplicate fixtures across `tests/integration/` and `tests/integration/real_models/` — all consume `setup_test_db` and produce an authenticated `AsyncClient`
- Each duplicate takes `setup_test_db` as a parameter (redundant — the canonical fixture doesn't need it since `client` fixture already depends on `setup_test_db`)

### How pytest fixture resolution works

When a test function has a parameter named `auth_client`, pytest resolves it by:
1. Looking in the test file's module for a fixture with that name
2. Looking in `conftest.py` files in the same directory, then parent directories
3. If a fixture is defined both locally AND in a parent conftest, the **local definition wins**

This means every file with a local `async def auth_client(...)` is actively overriding the canonical version. Deleting the local definition causes pytest to fall through to the parent conftest — no imports needed.

## Goals / Non-Goals

**Goals:**
- Delete all 17 remaining duplicate `auth_client` fixture definitions, making the canonical fixture in `tests/integration/conftest.py` the single source of truth across all integration test files
- Ensure zero behavior change — every test that uses `auth_client` gets the same or better behavior from the canonical fixture
- Verify no regressions with a full integration test suite run

**Non-Goals:**
- Not modifying the canonical `auth_client` fixture itself (already proven correct)
- Not modifying any test logic (no test rewriting, no new tests)
- Not modifying `test_cache_bug.py` (already verified it uses `test_user_client`, not `auth_client` — handled in prior change)
- Not adding flaky markers or any other test infrastructure changes
- Not fixing the 4 intentionally skipped `test_link_aware_rag` tests

## Decisions

### Decision 1: Delete-only approach — no fixture rewriting

**Choice**: For each of the 17 files, delete the `auth_client` fixture definition in its entirety. Do not replace it with an import or any other code.

**Rationale**: pytest conftest resolution handles this automatically. The canonical `auth_client` lives in `tests/integration/conftest.py`, which is in the parent directory of all affected test files (including `real_models/` subdirectory). Deleting the local definition causes pytest to resolve `auth_client` from the parent conftest on the next test run.

**Alternatives considered**:
- Adding explicit `from conftest import auth_client` — redundant, conftest resolution already works, and explicit imports can cause circular dependency issues
- Rewriting each fixture to delegate to the canonical one — unnecessary complexity for a cleanup task

### Decision 2: Real_models/conftest.py deletion is safe

**Choice**: Delete `auth_client` from `tests/integration/real_models/conftest.py` (line 32) just like all the other files.

**Rationale**: In pytest, conftest fixtures resolve up the directory tree. `tests/integration/conftest.py` is a parent of `tests/integration/real_models/conftest.py` in the directory hierarchy. Deleting the `real_models/conftest.py` version means all tests in `real_models/` will inherit the canonical `auth_client` from `tests/integration/conftest.py`. The `real_models/conftest.py` file will still exist (it may define other fixtures) — only the `auth_client` definition is removed.

### Decision 3: Single batch operation — no phasing

**Choice**: Delete all 17 fixtures in one pass, then verify with a single full integration suite run.

**Rationale**: The operation is mechanical and identical across all files. There's no dependency between files, no rollout risk, and no incremental value in phasing. The prior change proved the canonical fixture works correctly with 6 already-deleted files. A single `grep` pass confirms no local `auth_client` remains, and a full `tests/integration/` run proves nothing regressed.

## Risks / Trade-offs

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| A file defines a `client` fixture that depends on its own `auth_client` (in addition to defining auth_client) — deleting auth_client breaks `client` | Low | Audit each file individually. If a file defines both `client` and `auth_client`, verify `client` doesn't depend on the local `auth_client`. If it does, update the dependency to use the canonical fixture. |
| A test in `real_models/` uses `setup_test_db` directly alongside `auth_client` and the canonical fixture's different parameter list causes a conflict | Low | The canonical `auth_client` takes `client: AsyncClient` (not `setup_test_db`). If any test depends on the fixture consuming `setup_test_db`, this is a subtle break. Mitigation: grep for tests that explicitly pass `setup_test_db` as an argument alongside `auth_client`. |
| Missing import in a file that currently relies on its own fixture packaging both `setup_test_db` and auth: the canonical fixture doesn't re-export `setup_test_db` | Low | Tests that need `setup_test_db` directly should declare it as a separate fixture parameter. The canonical `auth_client` already depends on `client` → `setup_test_db`, so the DB is still initialized. |
| One or more of the 17 files has already been partially modified and the `auth_client` fixture is no longer contiguous | Very Low | Read each file before editing. If the fixture has been modified to not match the standard pattern, evaluate whether it provides unique behavior. If so, handle as an exception. |

## Verification Plan

1. **Pre-flight**: Confirm `grep -n "async def auth_client" tests/integration/ | grep -v conftest.py` shows exactly 17 lines (baseline)
2. **Delete all 17 fixtures** across all target files
3. **Post-deletion check**: Confirm same grep returns 0 lines (or only `tests/integration/conftest.py`)
4. **Run all integration tests**: `uv run pytest tests/integration/ -v --tb=short -q`
5. **Run full suite (fast)**: `uv run pytest -m "not slow" -v --tb=short -q`
6. **Lint check**: `uv run ruff check tests/`
