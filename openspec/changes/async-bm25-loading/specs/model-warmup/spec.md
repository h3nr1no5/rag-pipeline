# Model Warmup

## Purpose

This delta spec updates the existing `model-warmup` capability to load models concurrently instead of sequentially.

## MODIFIED Requirements

### Requirement: System SHALL warm up models on startup

The system SHALL warm up all 4 models (cross_encoder, llm, embedder, dspy_lm) **concurrently** during server startup via `asyncio.create_task`. Loading SHALL be non-blocking (run in `asyncio.to_thread`) so the server accepts requests immediately. The system SHALL track warmup status in a unified `WarmupState` singleton using a dictionary keyed by model name, where each entry is a `ModelStatus` with fields: `model` (name string), `status` (`queued`, `loading`, `ready`, `error`, `permanent_error`), `progress` (0-100 integer), `message` (status text like "Downloading..."), and `error` (error detail string).

#### Scenario: All 4 models load concurrently in background during startup
- **WHEN** the server starts
- **THEN** the warmup tasks SHALL be launched via `asyncio.create_task` in the FastAPI lifespan handler
- **THEN** all model loading tasks SHALL be collected via `asyncio.gather()` for concurrent execution
- **THEN** the server SHALL accept HTTP requests before warmup completes
- **THEN** the effective cold-start time SHALL be `max(cross_encoder_time, llm_time, embedder_time, dspy_lm_time)` rather than the sum of all four

#### Scenario: Cross-encoder loads via thread pool
- **WHEN** the warmup task runs
- **THEN** the cross-encoder model (`CrossEncoder`) SHALL be instantiated inside `asyncio.to_thread()`
- **THEN** the singleton `_model` attribute on `CrossEncoderReranker` SHALL be set after loading completes
- **THEN** WarmupState for `"cross_encoder"` SHALL have `status="ready"` and `progress=100`

#### Scenario: LLM loads via thread pool
- **WHEN** the warmup task runs
- **THEN** the LLM model SHALL be instantiated inside `asyncio.to_thread()` via `get_llm()`
- **THEN** subsequent calls to `get_llm()` SHALL return the already-loaded singleton
- **THEN** WarmupState for `"llm"` SHALL have `status="ready"` and `progress=100`

#### Scenario: Embedder loads asynchronously via thread pool
- **WHEN** the warmup task runs
- **THEN** the embedder (`SentenceTransformerEmbedder`) SHALL be instantiated inside `asyncio.to_thread()`
- **THEN** the `_embedder_instance` module global SHALL be set after loading completes
- **THEN** subsequent calls to `get_embedder()` SHALL return the already-loaded instance without blocking
- **THEN** WarmupState for `"embedder"` SHALL have `status="ready"` and `progress=100`

#### Scenario: DSPy LM warms up instantly after LLM
- **WHEN** the warmup task runs
- **AND** the LLM model is `"ready"`
- **THEN** `get_mlx_dspy_lm()` SHALL be called to instantiate the DSPy LM wrapper
- **THEN** WarmupState for `"dspy_lm"` SHALL be set to `status="ready"` and `progress=100` immediately
- **THEN** no actual model loading SHALL occur (DSPy LM wraps the existing MLX LLM)

#### Scenario: Warmup is idempotent
- **WHEN** the server starts with models already loaded
- **THEN** the warmup task SHALL skip re-initialization of already-loaded singletons
- **THEN** WarmupState SHALL reflect the already-loaded state
