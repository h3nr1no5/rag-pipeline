# Model Warmup

## Purpose

Ensure that cross-encoder reranker and LLM models are loaded in the background during server startup, exposing status via a health endpoint so the frontend can display loading progress and handle errors gracefully.

## Requirements

### Requirement: System SHALL warm up models on startup

The system SHALL begin loading the cross-encoder reranker and LLM models during server startup via `asyncio.create_task`. Loading SHALL be non-blocking (run in `asyncio.to_thread`) so the server accepts requests immediately.

#### Scenario: Models load in background during startup
- **WHEN** the server starts
- **THEN** the warmup task SHALL be launched via `asyncio.create_task` in the FastAPI lifespan handler
- **THEN** the server SHALL accept HTTP requests before warmup completes

#### Scenario: Cross-encoder loads via thread pool
- **WHEN** the warmup task runs
- **THEN** the cross-encoder model (`CrossEncoder`) SHALL be instantiated inside `asyncio.to_thread()`
- **THEN** the singleton `_model` attribute on `CrossEncoderReranker` SHALL be set after loading completes

#### Scenario: LLM loads via thread pool
- **WHEN** the warmup task runs
- **THEN** the LLM model SHALL be instantiated inside `asyncio.to_thread()` via `get_llm()`
- **THEN** subsequent calls to `get_llm()` SHALL return the already-loaded singleton

#### Scenario: Warmup is idempotent
- **WHEN** the server starts with models already loaded
- **THEN** the warmup task SHALL skip re-initialization of already-loaded singletons

### Requirement: System SHALL expose model status via GET /health/models

The system SHALL provide a `GET /health/models` endpoint returning per-model loading status, model name, and progress.

#### Scenario: Health endpoint returns model list
- **WHEN** a client calls `GET /health/models`
- **THEN** the response SHALL contain status for each model: `cross-encoder` and `llm`
- **THEN** each model entry SHALL contain `status` (`loading`, `ready`, or `error`), `model` (model name string), and `progress` (0-100 integer)

#### Scenario: Progress updates during loading
- **WHEN** a model is loading
- **THEN** `progress` SHOULD increase from 0 to 100 as loading progresses
- **THEN** `status` SHALL be `"loading"`

#### Scenario: Ready state after loading
- **WHEN** a model finishes loading
- **THEN** `status` SHALL be `"ready"`
- **THEN** `progress` SHALL be `100`

#### Scenario: Error state on failure
- **WHEN** a model fails to load
- **THEN** `status` SHALL be `"error"`
- **THEN** the response MAY include an `error` field with a description

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
