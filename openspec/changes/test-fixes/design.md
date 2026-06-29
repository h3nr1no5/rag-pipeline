## Context

The integration test suite has **113 failures out of 208 tests** (54% failure rate). Investigation revealed:

```
Root cause (92%): ASGITransport(app=app) does NOT run FastAPI lifespan context manager
   → warmup_models() never called
   → WarmupState remains empty
   → require_models("embedder") returns None → 503
   → 69 upload tests fail + 18 query tests fail + 10 cascading failures

Actual bugs (8%):
  1. test_llm_loading.py calls state.update_llm() — method does not exist
  2. test_dspy_warmup.py — root conftest sets API_DOCS_DSPY_ENABLED=false,
     preventing DSPy LM warmup path from executing
  3. test_embedder_warmup.py — mock wiring doesn't propagate to
     warmup_models() assignment site
```

The `model-readiness` change (already complete) introduced the `require_models` gate and dict-based `WarmupState`, but never addressed how tests interact with this system. Existing workarounds are fragile: `test_health_models.py` manually seeds `state._models`, and `test_server_smoke.py` launches a subprocess (~8s setup).

No custom pytest markers are registered in `pyproject.toml`. Tests are organized only by directory, with no speed tiers, stability flags, or dependency annotations.

## Goals / Non-Goals

**Goals:**
- Fix the 113 integration test failures by seeding WarmupState in a session-scoped fixture
- Fix the 3 actual bugs (update_llm API, DSPy env var, embedder mock wiring)
- Register custom pytest markers for level, speed, stability, and dependency classification
- Skip the expensive subprocess-based `test_server_smoke.py` by default (mark as `slow`)
- Integration suite goes from 43% to ~96% passing

**Non-Goals:**
- Not adding a CI/CD pipeline (follow-up change)
- Not adding deterministic test selection (separate `deterministic-test-selection` change)
- Not tagging all 78 test files with markers (foundation only — tagging is task-level work within this change)
- Not fixing the 4 skipped `test_link_aware_rag` tests (intentionally skipped as NOT IMPLEMENTED)
- Not refactoring test infrastructure beyond what's needed for a green suite

## Decisions

### Decision 1: Session-scoped WarmupState seeding fixture

**Choice**: Add a `session`-scoped autouse fixture in `tests/integration/conftest.py` that pre-populates `WarmupState` with all 4 models in `"ready"` status before any test runs.

```python
@pytest_asyncio.fixture(scope="session", autouse=True)
async def prewarm_models():
    state = get_warmup_state()
    for name in ("cross_encoder", "llm", "embedder", "dspy_lm"):
        await state.update(name, status="ready", progress=100, model=name)
```

**Rationale**: This approach is already proven by `test_health_models.py` which uses the same pattern. It requires zero model downloads, zero GPU memory, runs in microseconds, and doesn't modify production code. The fixture is `session`-scoped so it runs once per test session, not once per test function.

**Alternatives considered**:
- Testing mode env var in `gate.py` — rejected because it modifies production code for test purposes. The fixture approach keeps concerns separated.
- Running real `warmup_models()` in tests — rejected because it requires 500MB+ model downloads, GPU, and adds minutes to test time.
- Function-scoped fixture — rejected because session-scoped is sufficient (WarmupState is a singleton) and avoids repeated overhead.

### Decision 2: Fix `test_llm_loading.py` — update_llm → update("llm")

**Choice**: Replace `await state.update_llm(status="loading", progress=0)` with `await state.update("llm", status="loading", progress=0)` and the `ready`/`error` variants.

**Rationale**: The `model-readiness` change replaced per-field methods (`update_cross_encoder`, `update_llm`) with a generic `update(model_name, **kwargs)`. This test was not updated to reflect that API change. It's a straightforward rename.

### Decision 3: Fix `test_dspy_warmup.py` — override env var

**Choice**: In each DSPy warmup test function, set `os.environ["API_DOCS_DSPY_ENABLED"] = "true"` before the warmup call, and restore it in a `finally` block or via a fixture.

**Rationale**: Root `conftest.py` sets `API_DOCS_DSPY_ENABLED=false` to prevent DSPy's internal `asyncio.run()` from conflicting with pytest-asyncio's running event loop. However, `warmup_models()` checks this setting and skips the DSPy LM warmup path entirely when it's false (line 320 of `src/domain/services/warmup.py`). The tests need this env var to be `true` to exercise that path.

**Risk**: Overriding the env var re-introduces the DSPy `asyncio.run()` conflict. Mitigation: DSPy LM warmup is lightweight (just wraps the already-loaded MLX LLM), so `asyncio.run()` is not called in this path — only `get_mlx_dspy_lm()` and `dspy.configure()`.

### Decision 4: Fix `test_embedder_warmup.py` — mock wiring investigation

**Choice**: Investigate and fix `_mock_all_warmup_deps()` in `test_embedder_warmup.py`. The function patches `warmup_models`'s import of `SentenceTransformerEmbedder` via `unittest.mock.patch`, but the mock may not propagate to the assignment site `emb_mod._embedder_instance = embedder` at line 301 of `warmup.py`.

**Likely fix**: Ensure the mock `SentenceTransformerEmbedder` constructor returns the expected `mock_embedder_instance` object, and that this propagated instance is what gets checked after `warmup_models()` completes. The fix may involve adjusting the patch target path or the assertion logic.

### Decision 5: Register custom pytest markers

**Choice**: Add marker definitions to `pyproject.toml` under `[tool.pytest.ini_options] markers`:

```toml
markers = [
    "unit: Pure logic tests, no I/O or database",
    "integration: Tests requiring database or service layer",
    "e2e: Full application bootstrap tests",
    "fast: Completes in under 0.5s",
    "slow: Takes 0.5s or longer (often LLM-dependent)",
    "flaky: Known to be intermittently unreliable",
    "needs_llm: Requires LLM model to be loaded",
    "needs_db: Requires database connection",
    "needs_disk: Requires file I/O (uploads, PDFs)",
]
```

**Rationale**: Markers enable `-m "fast"`, `-m "not slow and not flaky"`, and similar targeted test selection. Without registration, `pytest --strict-markers` (recommended for CI) rejects unknown markers. No tests are tagged yet — this change only registers them so tagging can follow.

### Decision 6: Move `test_server_smoke.py` behind `slow` marker

**Choice**: Decorate `TestServerSmoke` class with `@pytest.mark.slow`. This test launches a subprocess uvicorn server (~8s setup), which is too expensive for fast feedback loops.

**Rationale**: The smoke test validates real server startup, which is valuable for pre-deploy checks but wasteful for per-commit/agent runs. The `fast` marker suite (all other 1,270+ tests) runs in ~25s without it.

## Risks / Trade-offs

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Seeded WarmupState masks real model readiness bugs in production | Low | The seed fixture only affects integration tests. Production always runs `warmup_models()` via lifespan. The warmup logic itself is covered by `test_health_models.py` and `test_warmup.py`. |
| Session-scoped fixture crosses test isolation boundaries | Medium | `WarmupState` is a process-level singleton. If a test mutates it, that leaks to subsequent tests. Mitigation: mark the fixture as `autouse` but also add a cleanup step in each test's teardown, or ensure no test writes to WarmupState (they shouldn't need to). |
| DSPy `API_DOCS_DSPY_ENABLED=true` in test_dspy_warmup triggers `asyncio.run()` | Low | The DSPy LM warmup path only calls instantiation + configure, not `asyncio.run()`. The conflict only occurs in DSPy's internal pipeline initialization, which is disabled by the env var check. |
| Embedder mock fix is more complex than expected | Medium | If the patch target path doesn't match the actual import site, debugging may take time. Mitigation: use `warnings.warn` + `unittest.mock.patch(..., autospec=True)` to catch mismatches early. |
| `test_server_smoke.py` won't run in default CI | Intended | Use `pytest -m "slow"` in nightly CI or pre-deploy checks. |
