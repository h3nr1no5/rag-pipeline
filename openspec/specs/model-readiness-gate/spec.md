# Model Readiness Gate

## Purpose

Provide a centralized FastAPI dependency that checks model readiness before routing requests to query and document endpoints, returning HTTP 503 with `Retry-After` headers when required models are not yet available.

## Requirements

### Requirement: Gate SHALL check model status before route execution

The system SHALL provide a `require_models(*model_names: str)` FastAPI dependency that checks WarmupState for each specified model before the route handler executes.

#### Scenario: All required models ready
- **WHEN** a client sends a request to a route with `require_models("llm", "cross_encoder")`
- **AND** both models have status `"ready"`
- **THEN** the request SHALL proceed to the route handler
- **THEN** no 503 error SHALL be raised

#### Scenario: Model still loading
- **WHEN** a client sends a request to a route with `require_models("llm")`
- **AND** the LLM has status `"loading"`
- **THEN** the endpoint SHALL return HTTP 503
- **THEN** the response SHALL include a `Retry-After: 5` header
- **THEN** the response body SHALL contain an error message indicating the model is still loading

#### Scenario: Model in error state
- **WHEN** a client sends a request to a route with `require_models("cross_encoder")`
- **AND** the cross-encoder has status `"error"` or `"permanent_error"`
- **THEN** the endpoint SHALL return HTTP 503
- **THEN** the response SHALL include a `Retry-After: 10` header

#### Scenario: Multiple models required, one not ready
- **WHEN** a client sends a request to `/query/langchain` (requires `llm` and `cross_encoder`)
- **AND** the LLM is `"ready"` but the cross-encoder is `"loading"`
- **THEN** the endpoint SHALL return HTTP 503
- **THEN** the response SHALL indicate which model is not ready

### Requirement: Gate SHALL be applied to all query and document routes

Each backend route SHALL declare its model dependencies via the gate. Routes that require no models (health, auth, docs) SHALL NOT use the gate.

#### Scenario: Cosine query requires LLM
- **WHEN** a client calls `POST /query` or `POST /query/stream`
- **THEN** the route SHALL have `require_models("llm")` applied

#### Scenario: LangChain query requires LLM and cross-encoder
- **WHEN** a client calls `POST /query/langchain` or `POST /query/langchain/stream`
- **THEN** the route SHALL have `require_models("llm", "cross_encoder")` applied

#### Scenario: LlamaIndex query requires LLM
- **WHEN** a client calls `POST /query/llamaindex` or `POST /query/llamaindex/stream`
- **THEN** the route SHALL have `require_models("llm")` applied

#### Scenario: API docs query requires LLM and DSPy LM
- **WHEN** a client calls an API docs query route
- **THEN** the route SHALL have `require_models("llm", "dspy_lm")` applied

#### Scenario: Document upload requires embedder
- **WHEN** a client calls `POST /documents`
- **THEN** the route SHALL have `require_models("embedder")` applied

#### Scenario: Health and auth routes have no gate
- **WHEN** a client calls `GET /health`, `GET /health/models`, `POST /auth/*`, or `GET /docs`
- **THEN** no model readiness check SHALL be applied

### Requirement: Streaming endpoints SHALL gate at the top of the generator

Streaming endpoints (SSE) SHALL check model readiness inside the event generator, before yielding any data, because FastAPI `Depends` in the route signature does not apply to generator internals.

#### Scenario: Streaming query aborts early on 503
- **WHEN** a client calls `POST /query/stream`
- **AND** the LLM is loading
- **THEN** the generator SHALL yield `{"error": "Model 'llm' is still loading. Please try again."}` followed by `data: [DONE]\n\n`
- **THEN** the generator SHALL return immediately without proceeding to retrieval or LLM generation

### Requirement: Ad-hoc cross-encoder check SHALL be removed

The existing inline cross-encoder error check in `/query/langchain` and `/query/langchain/stream` SHALL be removed, as this responsibility is now handled by the unified gate.

#### Scenario: LangChain routes no longer have inline check
- **WHEN** code is deployed
- **THEN** `warmup_state.cross_encoder.status == "error"` check SHALL NOT appear in LangChain route handlers
- **THEN** the gate SHALL enforce all model checks uniformly
