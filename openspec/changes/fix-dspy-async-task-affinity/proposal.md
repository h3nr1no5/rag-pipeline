## Why

DSPy 3.x enforces async task affinity for `dspy.configure()` — it can only be called from the same `asyncio.Task` that first called it. Currently, the startup code calls `dspy.configure(lm=mldspy_lm)` from **two different async tasks**: the lifespan task (fallback in `main.py`) and the warmup task (`warmup_models()` in `warmup.py`). This causes a deterministic crash on every startup when `api_docs_enabled=True`.

The lifespan fallback always wins the race because `asyncio.create_task()` doesn't yield control, causing the warmup task's `dspy.configure()` to fail with the error:  
`"dspy.configure(...) can only be called from the same async task that called it first."`

## What Changes

- **Remove** the DSPy lifespan fallback block in `src/api/main.py` (the second `dspy.configure()` call), making `warmup_models()` the single source of truth for DSPy configuration
- **Add safeguard** in `src/domain/services/warmup.py` so that `dspy_lm` state is meaningfully set even if an earlier model (cross-encoder, LLM, embedder) fails permanently before the DSPy section is reached
- **Clean up** redundant test mocks in test files that patched the removed `dspy.configure()` call

## Capabilities

### New Capabilities

- _(none — this is a bug fix, no new capabilities)_

### Modified Capabilities

- _(none — implementation change only, no spec-level requirement changes)_

## Impact

- **`src/api/main.py`**: Remove ~20 lines (the DSPy configure fallback in the lifespan). The `import dspy` at module level stays (used elsewhere, or may become unused — verify during implementation).
- **`src/domain/services/warmup.py`**: Minor change — ensure `dspy_lm` status is set even when earlier models fail before the DSPy section.
- **Test files**: The `dspy.configure` mock/patch in `tests/integration/test_api_docs_e2e.py` becomes redundant — may be cleaned up.
- **No new dependencies.** No API changes. No breaking changes.
