## 1. Write regression test

- [x] 1.1 Create `tests/unit/test_dspy_startup_race.py` with a test that verifies `dspy.configure()` is NOT called during lifespan startup — this catches future reintroductions of the second call site
- [x] 1.2 Run the regression test BEFORE the fix to confirm it FAILS: `uv run pytest tests/unit/test_dspy_startup_race.py -v --tb=long`
  - Result: `AssertionError: Expected 'mock' to not have been called. Called 1 times. Calls: [call(lm=<MagicMock id='...'>)].` ✅

## 2. Remove lifespan DSPy fallback

- [x] 2.1 Remove the DSPy configure fallback block from `src/api/main.py` — the `if settings.api_docs_enabled:` block with `dspy.configure(lm=mlx_dspy_lm)`
- [x] 2.2 Remove `import dspy` from `main.py` (confirmed: no remaining code references; only a comment on line 9)
- [x] 2.3 Re-run the regression test to confirm it NOW PASSES: `uv run pytest tests/unit/test_dspy_startup_race.py -v --tb=long`
  - Result: `1 passed` ✅

## 3. Clean up test mocks

- [x] 3.1 In `tests/integration/test_api_docs_e2e.py`, remove the `patch("dspy.configure")` — it's redundant now that `dspy.configure` is only called in `warmup_models()`, which is already mocked
- [x] 3.2 Run the full test suite to confirm no regressions (`uv run pytest`)

## 4. Verify

- [x] 4.1 Confirm `uv run pytest tests/unit/test_warmup_state.py tests/unit/test_warmup_progress.py tests/unit/test_gate.py` still passes (47 unit)
  - Result: 47 passed ✅
- [x] 4.2 Confirm `uv run python -c "from src.api.main import app; print('App creates successfully')"` works without DSPy configure errors
