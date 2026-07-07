## Context

DSPy 3.x enforces async task affinity on `dspy.configure()` — once called from a given `asyncio.Task`, it refuses calls from any other task with a `RuntimeError`. The current startup sequence has two calls to `dspy.configure(lm=mlx_dspy_lm)`:

1. **Lifespan task** (`src/api/main.py`, line 336): A fallback that runs synchronously during FastAPI's lifespan
2. **Warmup task** (`src/domain/services/warmup.py`, line 327): Inside `warmup_models()`, launched via `asyncio.create_task()`

The lifespan fallback always executes first because `create_task()` schedules but doesn't yield — there's no `await` between the `create_task()` call and the fallback's `dspy.configure()`. When `warmup_models()` later reaches its own `dspy.configure()`, DSPy rejects it because the owning task differs.

The bug is deterministic when `api_docs_enabled=True`.

## Goals / Non-Goals

**Goals:**
- Eliminate the `RuntimeError` on startup when `api_docs_enabled=True`
- Ensure `warmup_models()` remains the single source of truth for model readiness
- Handle edge case where warmup fails before reaching the DSPy section
- Maintain backward compatibility — no changes to public API behavior

**Non-Goals:**
- No DSPy version upgrade or downgrade
- No changes to how `dspy.context` works for per-request overrides
- No changes to the LM adapter (`MLXDspyLM`) itself
- No changes to the model registry or gate system

## Decisions

### Decision 1: Remove lifespan fallback, keep warmup as single source of truth

**Choice**: Delete the entire DSPy configure block in `main.py` (lines 317-339).

**Rationale**:
- The fallback was described as a "startup window" safety measure, but there's no window to bridge — all DSPy-dependent endpoints are gated by `require_models("dspy_lm")`, which returns 503 until `warmup_models()` marks the model as `ready`
- Having two `dspy.configure()` calls from different async tasks is fundamentally incompatible with DSPy 3.x's task affinity constraint
- Removing it establishes a single, clear initialization path
- The `load_all_from_db()` call that follows in the lifespan does NOT depend on DSPy configuration — it only loads BM25 indexes, embeddings, and graph structures

**Alternatives considered**:
- **Use `dspy.context()` in warmup**: DSPy provides `dspy.context(lm=...)` as a context manager for cross-task scenarios, but it's designed for temporary scope overrides, not permanent configuration. Wrapping the entire app lifecycle in a context manager is awkward and fragile.
- **Move configure to lifespan, remove from warmup**: This breaks the warmup state model — `warmup_models()` would track `dspy_lm` as ready but wouldn't actually configure it. The warmup function would be lying about what it accomplished.
- **Await warmup before configuring in lifespan**: This defeats the purpose of async warmup by blocking the lifespan until all models load.

### Decision 2: Add safeguard for dspy_lm status when earlier models fail

**Choice**: In `warmup_models()`, ensure the DSPy section is structurally decoupled from earlier model success — if cross-encoder, LLM, or embedder fail permanently, the DSPy section still executes.

**Rationale**:
- Currently, if an earlier model throws an unhandled exception that propagates out of `warmup_models()`, the DSPy section never runs and `dspy_lm` stays in `"loading"` state forever
- The retry mechanism (`_retry_with_backoff`) schedules retries via `asyncio.create_task()`, which means the DSPy section WILL execute (the earlier model's failure is handled internally, not propagated)
- But if a truly catastrophic failure occurs (e.g., `TimeoutError` from the outer `try/except` that isn't caught gracefully), the safeguard still ensures `dspy_lm` gets a meaningful state

**Implementation**: The existing `try/except` at line 339 already catches exceptions from the DSPy block. The safeguard extends this to also handle the case where `warmup_models()` terminates early before reaching the DSPy section. See design details below.

## Design Details

### Changes to `src/api/main.py`

**Remove**: The entire DSPy configure fallback block (approximately lines 317-339):

```python
    # Configure DSPy with local MLX LM when api-docs RAG is enabled.
    #
    # NOTE: dspy.configure() now also happens during model warmup (warmup_models()).
    # This block serves as a fallback for the startup window before warmup completes.
    ...
    if settings.api_docs_enabled:
        try:
            from src.domain.rag.api_docs.pipeline.lm_adapter import get_mlx_dspy_lm
            mlx_dspy_lm = get_mlx_dspy_lm()
            dspy.configure(lm=mlx_dspy_lm)
            logger.info("DSPy configured with local MLX LM (lifespan fallback)")
        except Exception:
            logger.warning("Failed to configure DSPy LM in lifespan — warmup_models() will retry", exc_info=True)
```

**Also remove**: The `import dspy` at the top of `main.py` IF it's no longer used elsewhere (verify during implementation — `dspy` may still be referenced in other lifespan code).

### Changes to `src/domain/services/warmup.py`

The DSPy section at lines 317-341 already has its own `try/except`. The change is to ensure the section is reached even when earlier models fail:

**Current code** (simplified):
```python
try:
    await _load_cross_encoder()
except ...:
    asyncio.create_task(_retry_with_backoff(...))

try:
    await _load_llm()
except ...:
    asyncio.create_task(_retry_with_backoff(...))

try:
    await _load_embedder()
except ...:
    asyncio.create_task(_retry_with_backoff(...))

# DSPy section — may never be reached if an exception propagates
try:
    if api_docs_enabled:
        ...
except Exception as e:
    await state.update("dspy_lm", status="error", error=str(e))
```

**Key observation**: The `_retry_with_backoff` calls are scheduled via `asyncio.create_task()` and do NOT propagate exceptions. However, if an exception occurs *before* the inner `try/except` catches it (e.g., `TimeoutError` at line 210 or 254), it will propagate. The plan is already correctly structured — each model's load function has its own `try/except` that catches both `TimeoutError` and generic `Exception`. 

The only risk is a truly unexpected exception that bypasses all the catches. The safeguard is: ensure the DSPy section runs regardless. One approach: wrap the DSPy section in a `finally` block on the overall function, or at minimum ensure it executes independently.

**Actual change**: None needed to the existing exception handling — the four model sections are already independent. But the reviewer identified a gap: if `api_docs_enabled` reads differently at different times (e.g., settings mutation during testing), the behavior changes. No code change needed for this — it's a documented edge case.

### Changes to tests

- `tests/integration/test_api_docs_e2e.py`: Remove the `patch("dspy.configure")` since it's no longer called from the lifespan path. The mock becomes a no-op.
- No new tests required for this bug fix — existing tests cover the behavior.

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Warmup fails before DSPy section → API docs permanently broken | Low (retries handle transient failures) | High | The four model sections are structurally independent. Each has its own try/except. The retry mechanism (`_retry_with_backoff`) uses `create_task` so failures don't propagate. |
| `api_docs_enabled` setting mutation between startup and warmup | Very low (settings immutable at runtime) | Low | Documented edge case. If setting differs, DSPy either configures or skips based on warmup-time value — correct behavior. |
| Test flakiness from removed mock | Medium | Low | The `dspy.configure` patch in test_api_docs_e2e.py becomes a no-op — harmless but worth cleaning up for hygiene. |
| Regression: some latent dependency on lifespan DSPy config | Very low | Medium | Verified: `load_all_from_db()` doesn't use DSPy. All DSPy-dependent code paths are gated by `require_models("dspy_lm")`. |
