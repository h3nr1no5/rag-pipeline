## Why

The `WarmupState` system (`src/domain/services/warmup.py`) and its `require_models` gate (`src/api/gate.py`) create a false sense of readiness: the gate says "model ready" but the actual singleton (`_embedder_instance`) is still `None`. This architectural disconnect is the root cause of 71 test failures — the `prewarm_models` fixture seeds the gate but not the singletons, so background document processing blocks on real model loading. Removing the WarmupState layer simplifies the architecture, eliminates the source of these cascading failures, and makes the test suite trustworthy.

## Approach

This change uses a **hybrid approach**:
1. **`git revert 27952c7`** — undoes the commit that introduced WarmupState/require_models. Handles ~70% of the work (deletes gate.py, removes require_models from routes, removes test files that 27952c7 created).
2. **Manual cleanup** — removes files created by subsequent commits (test files from `198b8f2`, `4b14543`), cleans up `get_warmup_state` references that the revert restored, creates the inlined `_load_models()` in the lifespan.

## What Changes

**Deleted by `git revert 27952c7` (6 files):**
- `src/api/gate.py` — the `require_models` FastAPI dependency factory
- `tests/integration/test_health_models.py` — health endpoint model tests
- `tests/integration/test_query_gate.py` — gate integration tests
- `tests/unit/test_gate.py` — require_models unit tests
- `tests/unit/test_warmup_progress.py` — warmup progress bar tests
- `tests/unit/test_warmup_state.py` — WarmupState unit tests

**Deleted manually (5 files):**
- `src/domain/services/warmup.py` — the restored old WarmupState (cross-encoder + LLM only) plus the remaining embedder/DSPy retry logic from `198b8f2`. Replaced by inlined `_load_models()` in lifespan.
- `tests/integration/test_document_gate.py` — document gate tests (created by `198b8f2`)
- `tests/unit/test_model_status.py` — 36 ModelStatus tests (created by `198b8f2`)
- `tests/unit/test_warmup.py` — 24 old WarmupState tests (survived revert, but WarmupState is being removed)
- `tests/unit/test_dspy_startup_race.py` — async task race test (created by `4b14543`)

**Modified source files (6):**
- `src/api/main.py` — lifespan no longer imports `warmup_models()`; model loading logic inlined directly as `_load_models()`
- `src/api/routes/query/routes.py` — `require_models` import + `Depends()` already removed by revert; also remove 4 inline `get_warmup_state` cross-encoder checks that the revert restored
- `src/api/routes/documents.py` — `require_models` import + `Depends()` already removed by revert — clean
- `src/domain/rag/api_docs/routes.py` — `require_models` import + `Depends()` already removed by revert — clean
- `src/api/routes/health.py` — replace `get_warmup_state()` check (restored by revert) with direct singleton checks
- `src/domain/services/embedding.py` — already reverted to original `if _embedder_instance is None` lazy-load — clean

**Modified test files (5):**
- `tests/integration/conftest.py` — remove `prewarm_models` fixture (no longer needed)
- `tests/integration/test_dspy_warmup.py` — remove `get_warmup_state` assertions; update imports
- `tests/integration/test_embedder_warmup.py` — remove `get_warmup_state` assertions; focus on singleton assignment
- `tests/integration/test_llm_loading.py` — remove `state.update("llm", ...)` calls and `get_warmup_state`
- `tests/integration/test_api_docs_e2e.py` — remove `patch("src.domain.services.warmup.warmup_models", ...)` (module no longer exists)

## Capabilities

### New Capabilities
- `startup-model-loading`: Raw model initialization logic extracted from `warmup_models()` — loads cross-encoder, LLM, embedder, and DSPy LM at server startup via the FastAPI lifespan, setting the actual module-level singletons (`_embedder_instance`, `_llm_instance`) without intermediate state tracking.

### Removed Capabilities
- `model-readiness-gate`: The `require_models` FastAPI dependency that gated endpoint access based on `WarmupState` status. No longer needed — endpoints either have a loaded singleton or fail naturally with the underlying error.
- `warmup-state-tracking`: The `WarmupState` singleton, `ModelStatus` dataclass, progress callbacks, and retry-with-backoff logic. Replaced by direct model loading in the lifespan with simple try/except error handling.

## Impact

- **Simpler architecture**: No more decoupled gate/singleton problem. `_embedder_instance` is the single source of truth for embedder availability.
- **~140 lines deleted** from source (`gate.py` + `warmup.py`)
- **~500 lines deleted** from tests (6 test files removed, test files simplified)
- **Route handlers cleaned up**: No `require_models` dependency on every query/document route
- **prewarm_models fixture gone**: Integration tests no longer need this workaround — `require_models` doesn't exist, so there's nothing to pre-warm at the gate level
- **Health endpoint changes**: Instead of checking `WarmupState.to_dict()`, the health endpoint checks actual singleton existence — more honest reporting
- **warmup_models() preserved**: The model loading logic is extracted from `warmup.py` and inlined into the FastAPI lifespan. No production warmup behavior is lost.
