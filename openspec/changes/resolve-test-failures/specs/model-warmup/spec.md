## ADDED Requirements

### Requirement: Model loading runs in lifespan background task

The system SHALL load models (cross-encoder, LLM, embedder, DSPy LM) in a background `asyncio.create_task` during the FastAPI lifespan startup. Each model SHALL be loaded independently — if one model fails, the others SHALL still be attempted. Production warmup behavior SHALL be unchanged.

#### Scenario: Models loaded on server start
- **WHEN** the FastAPI server starts
- **THEN** `_load_models()` SHALL be invoked via `asyncio.create_task`
- **AND** the startup SHALL not block waiting for models

#### Scenario: Individual model failure is tolerated
- **WHEN** one model fails to load (e.g., cross-encoder)
- **THEN** the other models SHALL still be attempted
- **AND** the server SHALL still accept requests

#### Scenario: Test seeding prevents real model loading
- **WHEN** the test session starts
- **THEN** the singleton-seeding fixture SHALL set `_embedder_instance` before any background task can begin real model loading
- **AND** no test-only code SHALL execute during production startup
