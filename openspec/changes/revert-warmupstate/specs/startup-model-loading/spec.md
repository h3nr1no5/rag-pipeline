# startup-model-loading

Model initialization logic loaded during the FastAPI lifespan, setting module-level singletons directly without intermediate state tracking.

## ADDED Requirements

### Requirement: Models load at server startup via lifespan background task

The system SHALL load all models during server startup using a background task created in the FastAPI lifespan. The following models SHALL be loaded:

- Cross-encoder reranker
- LLM (via `get_llm()`)
- Embedder (assigned to `_embedder_instance`)
- DSPy LM (if `settings.api_docs_enabled` is True)

Each model SHALL be loaded in its own try/except block such that failure of one model does NOT prevent other models from loading. Errors SHALL be logged but SHALL NOT crash the server startup.

#### Scenario: All models load successfully during startup

- **WHEN** the FastAPI lifespan starts and background model loading completes
- **THEN** `_embedder_instance`, `_llm_instance`, cross-encoder, and DSPy LM are all initialized and set

#### Scenario: One model fails during startup loading

- **WHEN** the embedder fails to load during startup
- **THEN** the cross-encoder, LLM, and DSPy LM still load successfully
- **THEN** the embedder failure is logged with `logger.error`

### Requirement: Module-level singletons are the single source of truth

The system SHALL use module-level singletons (`_embedder_instance`, `_llm_instance`) as the single source of truth for model availability. No separate state-tracking layer SHALL exist alongside the singletons.

#### Scenario: Singleton reflects actual model state

- **WHEN** a model has been loaded
- **THEN** its module-level singleton SHALL be set to the model instance (not None)
- **WHEN** a model has not been loaded
- **THEN** its module-level singleton SHALL be None

### Requirement: Health endpoint checks singletons directly

The health endpoint SHALL report model availability by checking whether each module-level singleton is None. This replaces the previous WarmupState-based reporting.

#### Scenario: Health endpoint reports embedder loaded

- **WHEN** `_embedder_instance` is not None
- **THEN** the health response SHALL indicate the embedder is available

#### Scenario: Health endpoint reports embedder not loaded

- **WHEN** `_embedder_instance` is None
- **THEN** the health response SHALL indicate the embedder is not yet available

## REMOVED Requirements

### Requirement: Model readiness gate (require_models FastAPI dependency)

**Reason**: The `require_models` FastAPI dependency provided endpoint-level gating based on `WarmupState` status, but the gate and the actual model singletons were decoupled — the gate could report "ready" while the singleton was still `None`. This created a false sense of readiness and was the root cause of cascading test failures.

**Migration**: Remove all `Depends(require_models(...))` usages from route handlers. Remove the `require_models` factory and the `gate.py` module. Endpoints no longer have a model-readiness gate; if a model is not loaded, the endpoint produces a natural error from the missing singleton.

### Requirement: WarmupState tracking (WarmupState, ModelStatus, progress callbacks)

**Reason**: The `WarmupState` singleton tracked model loading progress via `ModelStatus` values, progress callbacks, and retry-with-backoff logic. This state-tracking layer was separate from the actual module-level singletons, allowing drift between reported and actual model availability.

**Migration**: Remove the `WarmupState` class, `ModelStatus` enum, `get_warmup_state()` function, `_warmup_state` module-level singleton, `_retry_with_backoff` retry logic, `_make_progress_callback` callback factory, and the progress callback protocol. Model loading is inlined into the lifespan with simple try/except error handling. The `prewarm_models` test fixture is also removed.
