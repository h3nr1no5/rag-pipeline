## Context

This change builds on work from four prior test-infra changes:

| Change | Status | What it addressed |
|--------|--------|-------------------|
| `test-fixes` | Active | WarmupState seeding fixture, LLM API bug, DSPy env var, embedder mock, marker registration |
| `resolve-test-failures` | Active | Embedding loading async wrap, singleton seeding, test doubles (TestEmbedder/TestLLM) |
| `fix-flaky-progress-tests` | Archived | Background task racing in `test_documents_progress.py` assertion windows |
| `test-hygiene` | Archived | Stale DB file accumulation, fixture consolidation, background task teardown |

Despite these fixes, **9+ tests remain flaky** in batch runs due to three isolation gaps not covered by prior work.

### Root Cause Analysis

**Gap 1: DB teardown race on macOS — `asyncio.sleep(0.05)` is insufficient**

The `setup_test_db` fixture in `tests/conftest.py` (line 183) already calls `await new_engine.dispose()` and waits `await asyncio.sleep(0.05)` before removing the `.db` file. However, benchmarking shows this sleep is insufficient on macOS:

- `engine.dispose()` closes the SQLAlchemy connection pool but the underlying `aiosqlite` worker thread may still hold the file descriptor for a few more scheduler ticks.
- `os.remove()` succeeds (unlinks the directory entry) while the old FD is still open, so SQLite's file data blocks remain allocated.
- When the next test creates a NEW engine at a different path (`_test_db_counter + uuid`), it should be unaffected — but in practice, macOS's `fcntl`-based advisory locks can linger on recycled inodes under heavy async scheduler load, causing the new engine's first write to hit `SQLITE_READONLY`.

The fix is to replace the fixed `asyncio.sleep(0.05)` with a **retry loop** that polls until the file can be removed (or a short timeout expires), and to add `gc.collect()` to release any Python-level references that keep the aiosqlite worker alive.

```
Test A ──→ engine.dispose() ──→ asyncio.sleep(0.05) ──→ os.unlink(db_path)
                                                          ↑ macOS fcntl lock still held by aiosqlite worker thread
Test B ──→ create_async_engine(new_path) ──→ SQLITE_READONRY ✗
```

**Gap 2: auth_client is duplicated + buggy**

Seven test files each define a copy-pasted `auth_client` fixture that shadows the canonical one in `tests/integration/conftest.py`. The variant in `test_auth_flow.py` (lines 17-38) has a logic bug:

```python
response = await ac.post("/api/v1/auth/signup", json={...})
if response.status_code == 400:          # user already exists
    await ac.post("/api/v1/auth/login", json={...})
    # BUG: login response is IGNORED — token never extracted from response
    # Falls through to `yield ac` WITHOUT Authorization header → 401 on every call
elif response.status_code == 201:        # user created
    login_response = await ac.post(...)
    token = login_response.json()["access_token"]
    ac.headers["Authorization"] = f"Bearer {token}"
yield ac
```

The `if` branch (400 / UUID collision) discards the login result — the token is never set on `ac.headers`. The `elif` branch (201) correctly captures it. Since each test gets a unique DB (via `setup_test_db`), signup almost always returns 201, making the bug latent — until test-ordering coincidence triggers the 400 path.

Note: The canonical `auth_client` at `tests/integration/conftest.py:102-121` does NOT have this bug. The issue is purely that 6+ duplicate fixtures override it and one of them (in `test_auth_flow.py`) is buggy.

**Gap 3: MPNet tensor accumulation**

The `sentence-transformers/all-mpnet-base-v2` model allocates PyTorch tensors on CPU. These tensors keep Python object references alive through the `transformers` C extension. When many tests run in sequence (each loading the embedding model via `get_embedder()`), stale tensor references accumulate faster than CPython's generational GC can collect them. After ~5-10 iterations, memory pressure triggers a segfault in `transformers/models/mpnet/modeling_mpnet.py` C extension code.

Note: The `seed_singletons` fixture (session-scoped) now pre-seeds `_embedder_instance` with `TestEmbedder()`, so most integration tests never load the real model. The segfault occurs only in the subset of tests that explicitly exercise real model loading (e.g., `test_documents::test_upload_yaml_api_document`, `test_embedder_warmup`).

## Goals / Non-Goals

**Goals:**
- Eliminate the `readonly database` flaky failures: make engine disposal deterministic
- Eliminate the `401 Not Authenticated` flaky failures: single canonical auth_client with guaranteed token capture
- Eliminate the MPNet segfault: GC collection between embedding-heavy tests
- Document known flakiness with `@pytest.mark.flaky` markers for transparency until verified

**Non-Goals:**
- Not fixing the 4 intentionally skipped `test_link_aware_rag` tests (not implemented)
- Not adding `pytest-rerunfailures` plugin (fix root cause, don't retry)
- Not restructuring the test directory layout
- Not adding CI pipeline changes

## Decisions

### Decision 1: Robust DB file removal with retry loop

**Choice**: Replace the fixed `asyncio.sleep(0.05)` in `setup_test_db` teardown with a retry loop that polls `os.remove()` until it succeeds (or a short timeout expires). This addresses the root cause: macOS `fcntl`-based advisory locks held by the `aiosqlite` worker thread can outlive `engine.dispose()` by an unpredictable number of scheduler ticks.

```python
# Current (flaky):
await new_engine.dispose()
await asyncio.sleep(0.05)          # ← fixed sleep, non-deterministic on macOS
_remove_sqlite_file(db_path)

# Fixed:
await new_engine.dispose()
gc.collect()                        # ← release Python-level aiosqlite references

# Retry file removal with backoff (macOS fcntl lock may lag behind dispose())
for attempt in range(10):
    try:
        _remove_sqlite_file(db_path)
        break
    except PermissionError:
        if attempt == 9:
            raise                    # give up after 10 attempts (~500ms total)
        await asyncio.sleep(0.05 * (attempt + 1))  # linear backoff
```

Also add `import gc` at the top of `tests/conftest.py`.

**Rationale**: Polling `os.remove()` until it stops raising `PermissionError` is the only reliable way to handle the non-deterministic macOS fcntl lock release. The linear backoff (50ms, 100ms, 150ms, ... up to 500ms) gives the OS sufficient time while keeping the total pause under 500ms even in the worst case. `gc.collect()` ensures any Python objects keeping the aiosqlite worker thread alive are freed before the retry loop begins.

**Alternatives considered**:
- Increasing the fixed sleep to 500ms — rejected because it penalizes all tests (500ms × ~700 tests = 5.8min wasted) and still doesn't guarantee determinism
- Using in-memory SQLite (`:memory:`) — rejected because it prevents cross-test isolation (same-memory sharing) and doesn't work with aiosqlite's multi-connection pattern
- Switching to PostgreSQL in tests — overengineered for fixing a 50ms sleep

### Decision 2: Single canonical `auth_client` in integration conftest

**Choice**: Add one authoritative `auth_client` fixture in `tests/integration/conftest.py`, using an idempotent signup-then-always-login pattern. Delete all 6+ duplicates.

```python
@pytest.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """Idempotent auth_client: signup first, ALWAYS login, ALWAYS capture token."""
    email = f"test_{uuid4().hex[:8]}@example.com"
    password = "testpass123"

    # Signup — 400 means user already exists (benign), continue to login
    await client.post("/api/v1/auth/signup", json={
        "email": email, "password": password,
    })

    # ALWAYS login — this is the single source of truth for the token
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": password,
    })
    assert login_resp.status_code == 200, \
        f"Login failed: {login_resp.status_code} {login_resp.text}"

    token = login_resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
```

**Rationale**: This pattern is:
- **Idempotent**: Retry-safe (if signup worked, login works; if signup returned 400, login still works)
- **Self-healing**: Always captures a fresh token, never reuses a stale one
- **Zero branching**: No `if status_code == 400` branch that could be buggy or untested
- **Single source of truth**: One definition, imported by all tests. No drift.

**Files to delete duplicate from**:
- `tests/integration/test_auth_flow.py` — also fixes the bug
- `tests/integration/test_documents.py`
- `tests/integration/test_documents_integration.py`
- `tests/integration/test_query_flow.py`
- `tests/integration/test_cache_bug.py`
- `tests/integration/test_clear_embeddings.py`
- `tests/integration/test_score_normalization.py`

### Decision 3: Targeted GC collection

**Choice**: Add a `gc_after_embedding_tests` hook that triggers `gc.collect()` after any test that imports the embedding model. Detected via a marker or by monitoring `id(sentence_transformers)` changes.

**Implementation options considered**:

| Option | Complexity | Reliability |
|--------|-----------|-------------|
| A. Autouse fixture in root conftest that always GCs | Trivial (5 lines) | Overhead on every test (~2ms) |
| B. Marker-based: `@pytest.mark.needs_embedding` + hook | Medium (10 lines + tagging) | Zero overhead for non-embedding tests |
| C. Fixture imported by only embedding-heavy test files | Low (5 lines per file) | Manual but targeted |

**Chosen**: Option A — a lightweight autouse fixture in `tests/conftest.py` that runs `gc.collect()` unconditionally. Rationale: `gc.collect()` costs ~2ms and is negligible compared to test runtime (avg 0.5-10s per test). It's the simplest approach and provides universal protection.

```python
@pytest.fixture(autouse=True)
def collect_garbage():
    yield
    gc.collect()
```

### Decision 4: `@pytest.mark.flaky` as documentation

**Choice**: Add `@pytest.mark.flaky(reason="<specific root cause>")` to the 9 affected tests. This marker is already registered in `pyproject.toml` (from the `test-fixes` change) but has zero usage.

**Rationale**: Until the fix is verified by repeated CI runs, these tests are empirically flaky. The marker documents known instability, enables `pytest -m "not flaky"` for reliable runs, and creates a checklist for verification (all 9 markers should be removed once proven stable over 10 consecutive batch runs).

**Tests to mark**:
- `test_documents.py::test_upload_pdf_document` — `readonly database`
- `test_documents.py::test_upload_multiple_documents` — `401 Not Authenticated`
- `test_documents_integration.py::test_upload_python_guide` — `readonly database`
- `test_documents_integration.py::test_document_processing_status_updates` — `readonly database`
- `test_query_flow.py::test_list_selected_documents` — `401 Not Authenticated`
- `test_langchain_verification.py::TestLangChainStreaming` (all 3 methods) — state pollution
- `test_rag_pipelines_e2e.py::test_cosine_pipeline` — `readonly database`
- `test_clear_embeddings.py::test_clear_embeddings_then_reprocess` — `readonly database`
- `test_documents.py::test_upload_yaml_api_document` — MPNet segfault

## Implementation Plan

### Phase 1: Robust DB teardown (low risk, high impact)
1. Edit `tests/conftest.py` — replace fixed `asyncio.sleep(0.05)` with retry loop around `_remove_sqlite_file()`
2. Add `gc.collect()` after `await new_engine.dispose()` and before the retry loop
3. Add `import gc` at the top of `tests/conftest.py`
4. Verify by running `test_documents.py` + `test_documents_integration.py` + `test_rag_pipelines_e2e.py` + `test_clear_embeddings.py` in batch 3x

### Phase 2: Canonical auth_client (low risk, high impact)
1. Canonical `auth_client` already exists in `tests/integration/conftest.py:102-121` — no changes needed
2. Delete the 6 duplicate `auth_client` definitions from individual test files
3. Fix `test_auth_flow.py` auth_client bug: remove the duplicate, use imported canonical
4. Ensure `test_auth_flow.py` edge-case tests (signup failure paths) still work with canonical fixture — may need a separate custom fixture for those specific edge cases
5. Run auth + documents + query flow batch 3x to verify 401s are eliminated

### Phase 3: GC collection safety net (low risk, preventive)
1. Add `@pytest.fixture(autouse=True)` that runs `gc.collect()` after every test in `tests/conftest.py`
2. This prevents MPNet tensor accumulation AND any other Python-level reference leaks
3. Verify by running the full integration suite — GC overhead (~2ms/test) should be imperceptible

### Phase 4: Mark known flaky tests (documentation)
1. Add `@pytest.mark.flaky(reason="<specific root cause>")` to all 9 affected tests
2. Verify `pytest -m "not flaky"` excludes them
3. Verify `pytest -m "flaky"` includes exactly the 9 marked tests

### Phase 5: Verification
1. Run the known-flaky batch (`test_documents.py` + `test_documents_integration.py` + `test_query_flow.py` + `test_rag_pipelines_e2e.py` + `test_clear_embeddings.py` + `test_langchain_verification.py`) 3 times — expect 0 failures
2. Run full integration suite (`tests/integration/`) — expect 0 flaky failures
3. Run full suite (`-m "not slow"`) — expect 0 unexpected failures
4. Remove `@pytest.mark.flaky` from tests proven stable across all 3 runs

## Risks / Trade-offs

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `auth_client` deletion from individual test files breaks tests that depend on local `client` fixtures (e.g., `test_auth_flow.py` has its own `client` fixture that doesn't depend on the conftest's `auth_client`) | Medium | Audit each file individually. Some files define BOTH a `client` and `auth_client`. Only delete the `auth_client` duplicate; keep the `client` fixture if used for non-authenticated tests. |
| Retry loop masks a real SQLite corruption error by succeeding on a later attempt | Low | The retry loop only catches `PermissionError` (OS file lock). Real SQLite errors (`SQLITE_CORRUPT`, `SQLITE_IOERR`) propagate immediately. |
| `gc.collect()` causes a ~2ms overhead on every test | Low | 2ms × ~700 tests = 1.4s total. Negligible. |
| `test_auth_flow.py` edge-case tests rely on the local `auth_client`'s branching logic (400 vs 201) | Low | Those tests test signup-validation errors (e.g., invalid email format), which return 422 before any DB write. The 400-vs-201 branching in auth_client is irrelevant to them. |
| Existing `flaky` marker already in `pyproject.toml` but `@pytest.mark.flaky` may not work with `--strict-markers` | Low | The marker is already registered. No conflict. |

## Verification Plan

1. **Batch stability test**: Run `uv run pytest tests/integration/test_documents.py tests/integration/test_documents_integration.py tests/integration/test_query_flow.py tests/integration/test_rag_pipelines_e2e.py tests/integration/test_clear_embeddings.py tests/integration/test_langchain_verification.py -v --tb=short` 3 times
2. **Full integration run**: `uv run pytest tests/integration/ -v --tb=short` — should have 0 flaky failures
3. **Full suite**: `uv run pytest -v -m "not slow" --tb=short` — should match expected counts
4. **Confidence check**: `uv run pytest -m "flaky" -v` — should list exactly the 9 known flaky tests
