## 1. Setup — Marker registration

- [x] 1.1 Add `[tool.pytest.ini_options] markers` list to `pyproject.toml` with all 9 markers (unit, integration, e2e, fast, slow, flaky, needs_llm, needs_db, needs_disk)
- [x] 1.2 Verify markers appear in `uv run pytest --markers` output
- [x] 1.3 Verify no existing tests break `--strict-markers` (all current markers are `@pytest.mark.asyncio` which is built-in)

## 2. Fix integration test suite — WarmupState seeding fixture

- [x] 2.1 Add `pytest_asyncio` fixture `prewarm_models` in `tests/integration/conftest.py` with `scope="session"` and `autouse=True"
- [x] 2.2 Fixture imports `get_warmup_state` from `src.domain.services.warmup` and calls `state.update(name, status="ready", progress=100)` for each of the 4 models
- [x] 2.3 Run integration tests and verify 503 failures drop from 97 to 0 (the 92% root cause is fixed)
- [x] 2.4 Confirm fixture completes in under 10ms (no model loading occurs)

## 3. Fix bug — `test_llm_loading.py` update_llm API

- [x] 3.1 Replace `await state.update_llm(status="loading", progress=0)` with `await state.update("llm", status="loading", progress=0)` (line 54)
- [x] 3.2 Replace `await state.update_llm(status="ready", progress=100)` with `await state.update("llm", status="ready", progress=100)` (line 62)
- [x] 3.3 Replace `await state.update_llm(status="error", error=str(e))` with `await state.update("llm", status="error", error=str(e))` (line 65)
- [x] 3.4 Run `uv run pytest tests/integration/test_llm_loading.py -v --tb=short` and verify `test_llm_waits_for_ready` passes (or at least `AttributeError` is gone)

## 4. Fix bug — `test_dspy_warmup.py` env var conflict

- [x] 4.1 In each DSPy warmup test function, set `os.environ["API_DOCS_DSPY_ENABLED"] = "true"` before calling `warmup_models()`
- [x] 4.2 Add cleanup (restore or delete the env var) in a `finally` block or dedicated fixture
- [x] 4.3 Run `uv run pytest tests/integration/test_dspy_warmup.py -v --tb=short` and verify all 3 tests pass

## 5. Fix bug — `test_embedder_warmup.py` mock wiring

- [x] 5.1 Investigate `_mock_all_warmup_deps()` in `test_embedder_warmup.py`: trace the patch target path to verify it matches the import site in `warmup_models()` (line 282: `from .embedding import SentenceTransformerEmbedder`)
- [x] 5.2 Fix mock to propagate to `emb_mod._embedder_instance` assignment (line 301 of `warmup.py`)
- [x] 5.3 Run `uv run pytest tests/integration/test_embedder_warmup.py -v --tb=short` and verify all tests pass

## 6. Mark `test_server_smoke.py` as slow

- [x] 6.1 Add `@pytest.mark.slow` decorator to `TestServerSmoke` class
- [x] 6.2 Verify `uv run pytest -m "not slow"` excludes the smoke test
- [x] 6.3 Verify `uv run pytest -m "slow"` includes only the smoke test

## 7. Verify — Full suite green

- [x] 7.1 Run full integration suite: `uv run pytest tests/integration/ -v --tb=short -q` and confirm 503-related failures are eliminated
- [x] 7.2 Confirm only expected failures remain: the 3 real bugs (now fixed), 4 intentionally skipped link_aware_rag tests, and 4 cache skipif tests
- [x] 7.3 Run full test suite: `uv run pytest -v --tb=short -q` and confirm overall stability
- [x] 7.4 Update `AGENTS.md` quick commands to include `-m "not slow"` as the default test command
