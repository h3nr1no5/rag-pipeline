## ADDED Requirements

### Requirement: /health/models returns all four model statuses

The `/api/v1/health/models` endpoint SHALL return status for all four models: `cross_encoder`, `llm`, `embedder`, and `dspy_lm`. Each SHALL have a `{"status": "ready" | "loading"}` response. The endpoint SHALL check actual singleton/model state rather than a decoupled status tracker.

#### Scenario: All models ready

- **WHEN** all four models have finished loading (cross-encoder `_model` is set, LLM `_model` is not None, embedder singleton exists, DSPy LM singleton exists)
- **THEN** `/health/models` returns all four with `"status": "ready"`

#### Scenario: Models still loading

- **WHEN** one or more models have not yet finished loading
- **THEN** `/health/models` returns `"status": "loading"` for each model that is not yet ready

#### Scenario: Cross-encoder not tracked by WarmupState

- **WHEN** the cross-encoder model is ready
- **THEN** `cross_encoder.status` SHALL be `"ready"`, determined by checking `CrossEncoderReRanker._instance._model is not None`
- **WHEN** the cross-encoder model is not yet loaded
- **THEN** `cross_encoder.status` SHALL be `"loading"`

#### Scenario: DSPy LM conditionally reported

- **WHEN** `api_docs_enabled` is `True` and DSPy LM singleton has been created
- **THEN** `dspy_lm.status` SHALL be `"ready"`
- **WHEN** `api_docs_enabled` is `False`
- **THEN** `dspy_lm` SHALL be omitted from the response (or reported as `"disabled"`)
- **WHEN** `api_docs_enabled` is `True` but DSPy LM is not yet configured
- **THEN** `dspy_lm.status` SHALL be `"loading"`

### Requirement: LLM "ready" means weights are loaded

The LLM readiness check SHALL use `_llm_instance._model is not None` instead of `_llm_instance._model_loaded`. This ensures the endpoint only reports "ready" after model weights have been downloaded and loaded into memory.

#### Scenario: LLM reports ready after weight loading

- **WHEN** `_llm_instance._ensure_model_loaded()` has completed successfully (setting `_model` to the loaded model)
- **THEN** `/health/models` returns `"llm": {"status": "ready"}`

#### Scenario: LLM reports loading during weight download

- **WHEN** `_llm_instance` exists but `_model` is still `None` (weights not yet loaded)
- **THEN** `/health/models` returns `"llm": {"status": "loading"}`

#### Scenario: LLM reports loading when mlx_lm not available

- **WHEN** `_llm_instance` is `None` or `_model_loaded` is `False` (mlx_lm package not importable)
- **THEN** `/health/models` returns `"llm": {"status": "loading"}`

### Requirement: Frontend polling has bounded retry

The frontend polling loop SHALL use a 1-second interval between polls and SHALL stop after a maximum of 50 polls (~50 seconds total). When the maximum is reached, the frontend SHALL display a permanent error message and stop polling.

#### Scenario: Chat page polls at 1s interval

- **WHEN** models are not yet ready
- **THEN** the Chat page polls `/health/models` every 1 second (not 0.2 seconds)

#### Scenario: Chat page stops polling after 50 attempts

- **WHEN** 50 polls have been made without all models becoming ready
- **THEN** the Chat page SHALL stop polling and display an error message indicating models failed to load

#### Scenario: Chat page clears polling on success

- **WHEN** all polled models report `"ready"`
- **THEN** the Chat page SHALL set `st.session_state.models_ready = True`, clear the loading display, and stop rerunning

#### Scenario: model_status_banner has same polling behavior

- **WHEN** the Documents page uses `model_status_banner`
- **THEN** it SHALL poll at 1s intervals with a maximum of 50 polls, displaying a permanent error on exhaustion
