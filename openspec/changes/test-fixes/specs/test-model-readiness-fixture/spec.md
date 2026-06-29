# Test Model Readiness Fixture

## Purpose

Provide a session-scoped pytest autouse fixture that pre-populates `WarmupState` with all models in `"ready"` status, enabling integration tests to pass through the `require_models()` gate without running real model warmup.

## ADDED Requirements

### Requirement: Fixture SHALL seed WarmupState before any integration test runs

The system SHALL provide a `pytest_asyncio` fixture with `scope="session"` and `autouse=True` in `tests/integration/conftest.py` that seeds all 4 model entries (`cross_encoder`, `llm`, `embedder`, `dspy_lm`) in `WarmupState` with status `"ready"`.

#### Scenario: All models ready before first test
- **WHEN** the integration test session starts
- **THEN** `WarmupState` SHALL contain entries for `cross_encoder`, `llm`, `embedder`, and `dspy_lm`
- **THEN** each entry SHALL have `status == "ready"`
- **THEN** each entry SHALL have `progress == 100`

#### Scenario: Document upload proceeds without 503
- **WHEN** a test calls `POST /api/v1/documents/upload`
- **AND** the `prewarm_models` fixture has run
- **THEN** the endpoint SHALL NOT return HTTP 503 due to embedder not being ready
- **THEN** the request SHALL proceed to the route handler

#### Scenario: Query proceeds without 503
- **WHEN** a test calls `POST /api/v1/query`
- **AND** the `prewarm_models` fixture has run
- **THEN** the endpoint SHALL NOT return HTTP 503 due to LLM not being ready
- **THEN** the request SHALL proceed to the route handler

#### Scenario: Fixture runs once per session
- **WHEN** multiple integration tests run in the same session
- **THEN** the `prewarm_models` fixture SHALL execute only once (session scope)
- **THEN** `WarmupState` state SHALL persist across all tests in the session

### Requirement: Fixture SHALL NOT load real models

The fixture SHALL NOT call `warmup_models()` or any actual model loading code. It SHALL only set pre-computed status values directly on the `WarmupState` singleton.

#### Scenario: No model files downloaded
- **WHEN** the `prewarm_models` fixture runs
- **THEN** no model download calls SHALL be initiated
- **THEN** no Hugging Face Hub requests SHALL be made
- **THEN** the fixture SHALL complete in under 10ms

#### Scenario: No GPU or MLX initialization
- **WHEN** the `prewarm_models` fixture runs
- **THEN** no MLX or Metal GPU initialization SHALL occur
- **THEN** no sentence-transformers model loading SHALL occur
