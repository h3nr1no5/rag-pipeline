# Model Warmup

## Purpose

Ensure that cross-encoder, LLM, embedder, and DSPy LM models are loaded in the background during server startup. Warmup status is tracked in a unified WarmupState singleton and exposed via a health endpoint so the frontend can display per-model progress and handle errors gracefully.

## Requirements

### Requirement: System SHALL warm up models on startup

The system SHALL warm up all 4 models (cross_encoder, llm, embedder, dspy_lm) during server startup via `asyncio.create_task`. Loading SHALL be non-blocking (run in `asyncio.to_thread`) so the server accepts requests immediately. The system SHALL track warmup status in a unified `WarmupState` singleton using a dictionary keyed by model name, where each entry is a `ModelStatus` with fields: `model` (name string), `status` (`queued`, `loading`, `ready`, `error`, `permanent_error`), `progress` (0-100 integer), `message` (status text like "Downloading..."), and `error` (error detail string).

#### Scenario: All 4 models load in background during startup
- **WHEN** the server starts
- **THEN** the warmup task SHALL be launched via `asyncio.create_task` in the FastAPI lifespan handler
- **THEN** the warmup task SHALL load cross_encoder, llm, embedder, and dspy_lm
- **THEN** the server SHALL accept HTTP requests before warmup completes

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

#### Scenario: WarmupState uses dictionary registry
- **WHEN** the WarmupState singleton is accessed
- **THEN** models SHALL be stored in a `dict[str, ModelStatus]` keyed by model name
- **THEN** the `update(model_name, **kwargs)` method SHALL accept a model name string
- **THEN** the `get_status(model_name)` method SHALL return the `ModelStatus` for that model
- **THEN** the `to_dict()` method SHALL serialize all models

### Requirement: System SHALL expose model status via GET /health/models

The system SHALL provide a `GET /health/models` endpoint returning status for all 4 models (cross_encoder, llm, embedder, dspy_lm). Each model entry SHALL contain `status`, `model` (model name string), `progress` (0-100 integer), `message` (status text), and optionally `error`. Additionally, a `message` field SHALL provide a human-readable status description.

#### Scenario: Health endpoint returns all 4 models
- **WHEN** a client calls `GET /health/models`
- **THEN** the response SHALL contain status for all 4 models: `cross_encoder`, `llm`, `embedder`, `dspy_lm`
- **THEN** each model entry SHALL contain `status`, `model` (model name string), `progress` (0-100 integer), `message` (status text), and optionally `error`

#### Scenario: Progress updates during loading
- **WHEN** a model is loading
- **THEN** `progress` SHALL increase from 0 to 100 as loading/downloading progresses
- **THEN** `message` SHALL reflect the current phase (e.g., "Downloading...", "Loading into memory...")
- **THEN** `status` SHALL be `"loading"`

#### Scenario: Ready state after loading
- **WHEN** a model finishes loading successfully
- **THEN** `status` SHALL be `"ready"`
- **THEN** `progress` SHALL be `100`
- **THEN** `message` SHALL be empty or `"Ready"`

#### Scenario: Error state on failure
- **WHEN** a model fails to load
- **THEN** `status` SHALL be `"error"` (or `"permanent_error"` after repeated failures)
- **THEN** the response MAY include an `error` field with a description
- **THEN** `message` SHALL describe the retry state (e.g., "Error — retrying in 8s...")

### Requirement: Granular progress SHALL use HF Hub download callbacks

The system SHALL use real download progress from `huggingface_hub.snapshot_download()` callbacks to set granular 0-100 progress values, rather than coarse 0→50→100 jumps.

#### Scenario: Download progress updates via callback
- **WHEN** `snapshot_download()` is called during model warmup
- **AND** the model is not cached locally (download required)
- **THEN** a `progress_callback(downloads_started, downloads_total)` SHALL be passed to `snapshot_download()`
- **THEN** progress SHALL be computed as `int(downloads_started / downloads_total * 99)` (reserving 99-100 for load phase)
- **THEN** each callback invocation SHALL update WarmupState progress

#### Scenario: Cached model shows no granular progress
- **WHEN** `snapshot_download()` is called during model warmup
- **AND** the model is fully cached locally
- **THEN** the callback SHALL NOT fire (or fire once with 100%)
- **THEN** progress SHALL transition from 0 to 100 after model loads
- **THEN** this is acceptable because the load is near-instant

### Requirement: Auto-retry with exponential backoff SHALL recover from errors

When a model transitions to `"error"` status, the system SHALL automatically retry loading with exponential backoff: 2s, 4s, 8s, 16s, 30s (capped), repeating indefinitely. After 5 consecutive retries at the 30s cap, the model SHALL transition to `"permanent_error"`.

#### Scenario: First retry after error
- **WHEN** a model enters `"error"` status
- **THEN** the system SHALL schedule a retry after 2 seconds
- **THEN** the model status SHALL become `"loading"` during retry
- **THEN** the message SHALL indicate retry is in progress

#### Scenario: Exponential backoff increases delay
- **WHEN** a retry attempt fails
- **THEN** the next retry delay SHALL double (4s, 8s, 16s, 30s, ...)
- **THEN** the delay SHALL be capped at 30 seconds

#### Scenario: Permanent error after repeated failures
- **WHEN** a model has failed 5 consecutive retries at the 30s cap
- **THEN** the model SHALL transition to `"permanent_error"` status
- **THEN** no further automatic retries SHALL be scheduled
- **THEN** the error message SHALL indicate the model cannot be loaded

#### Scenario: Successful retry resets backoff
- **WHEN** a retry attempt succeeds
- **THEN** the model SHALL transition to `"ready"` status
- **THEN** the retry counter SHALL be reset
- **THEN** any subsequent error SHALL start from 2s backoff again

### Requirement: Cross-encoder failure SHALL return 503

If the cross-encoder model fails to load, the LangChain query endpoint SHALL return a 503 HTTP response with a clear error message.

#### Scenario: LangChain query with failed cross-encoder
- **WHEN** a client sends a query to `/api/v1/query/langchain`
- **AND** the cross-encoder model status is `"error"`
- **THEN** the endpoint SHALL return HTTP 503
- **THEN** the response body SHALL contain an error message indicating the reranker is unavailable

### Requirement: Score normalization SHALL be removed

The LangChain pipeline SHALL NOT apply min-max normalization to reranker scores. The raw softmax scores from the cross-encoder SHALL be passed through as-is.

#### Scenario: Scores pass through without normalization
- **WHEN** the LangChain backend returns search results
- **THEN** the `score` field in each result SHALL be the raw output of the cross-encoder
