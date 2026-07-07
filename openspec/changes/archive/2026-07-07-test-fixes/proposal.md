## Why

The integration test suite is broken: **113 of 208 tests fail or error** (54% failure rate). One root cause — the FastAPI `lifespan` context manager never runs under `ASGITransport(app=app)` — cascades into 92% of failures. Three additional real bugs account for the rest. This makes CI impossible, erodes trust in test results, and wastes developer time on noise. Before any test-selection, marker, or CI work can begin, the suite must be reliable.

## What Changes

- **WarmupState seeding fixture**: A session-scoped pytest fixture that pre-populates WarmupState with `"ready"` status for all 4 models (llm, cross_encoder, embedder, dspy_lm), bypassing the 503 gate in tests without running real model warmup
- **`test_llm_loading.py` bug fix**: Replace call to non-existent `state.update_llm()` with `state.update("llm", ...)`
- **`test_dspy_warmup.py` env var conflict fix**: Override `API_DOCS_DSPY_ENABLED` in DSPy warmup tests so they execute the DSPy LM warmup path regardless of the root conftest's override
- **`test_embedder_warmup.py` mock wiring fix**: Correct `_mock_all_warmup_deps()` so mocks propagate through the import chain to where `warmup_models()` assigns `_embedder_instance`
- **pytest marker registration**: Register custom markers (`unit`, `integration`, `e2e`, `fast`, `slow`, `flaky`, `needs_llm`, `needs_db`) in `pyproject.toml`
- **Skip `test_server_smoke.py` by default**: Move to a `slow` marker so fast CI runs skip the subprocess-based smoke test

## Capabilities

### New Capabilities
- `test-model-readiness-fixture`: Session-scoped pytest fixture that seeds WarmupState with all models in `"ready"` state, enabling integration tests to pass without model loading
- `test-marker-taxonomy`: Registered custom pytest markers for level, speed, stability, and dependency classification

### Modified Capabilities
- *(none — fixing test infrastructure, not changing spec-level behavior)*

## Impact

- **`tests/integration/conftest.py`**: Add session-scoped `prewarm_models` autouse fixture
- **`tests/integration/test_llm_loading.py`**: Fix `state.update_llm()` → `state.update("llm", ...)` API call
- **`tests/integration/test_dspy_warmup.py`**: Override `API_DOCS_DSPY_ENABLED` env var before warmup runs
- **`tests/integration/test_embedder_warmup.py`**: Fix mock wiring for `_embedder_instance` assignment
- **`pyproject.toml`**: Register custom pytest markers under `[tool.pytest.ini_options]`
- **~92% of integration test failures eliminated** — suite goes from 43% passing to ~96% passing
- No new dependencies (all tools are standard pytest features)
