## MODIFIED Requirements

### Requirement: Pipeline SHALL propagate rationale from DSPy predictor

The `APIDocRAG.forward()` method SHALL capture `response.reasoning` from the `APIResponseGenerator` ChainOfThought predictor and include it in the return dict. The `ApiDocPipelineManager._build_dspy_response()` method SHALL map this value to the `reasoning_hint` field of `ApiDocQueryResponse`. The async `APIDocRAG.aforward()` method SHALL do the same.

#### Scenario: Rationale captured in pipeline output
- **WHEN** `APIDocRAG.forward()` completes the generation stage
- **THEN** the returned dict SHALL include a `"rationale"` key with the DSPy rationale value
- **AND** this value SHALL be a non-empty string when the DSPy path succeeds

#### Scenario: Rationale captured in async pipeline output
- **WHEN** `APIDocRAG.aforward()` completes the generation stage
- **THEN** the returned dict SHALL include a `"rationale"` key with the DSPy rationale value
- **AND** this value SHALL be a non-empty string when the DSPy path succeeds

#### Scenario: Rationale mapped to ApiDocQueryResponse
- **WHEN** `_build_dspy_response()` constructs the response from either `forward()` or `aforward()` output
- **THEN** the `ApiDocQueryResponse.reasoning_hint` field SHALL be set from the `"rationale"` value

#### Scenario: Fallback path sets empty reasoning_hint
- **WHEN** `_query_fallback()` generates a response
- **THEN** the `ApiDocQueryResponse.reasoning_hint` field SHALL be an empty string

## ADDED Requirements

### Requirement: DSPy pipeline SHALL support native async execution

The `APIDocRAG` module SHALL provide an `async def aforward()` method that runs the full retrieval-generation pipeline using `await` for all async operations, eliminating `asyncio.run()` from the hot path. The `MLXDspyLM` adapter SHALL provide a matching `async def aforward()` method that delegates directly to `await self._llm.generate()`.

#### Scenario: Async pipeline returns identical response shape
- **WHEN** `aforward()` is called with the same question and parameters as `forward()`
- **THEN** the returned dict SHALL contain the same keys: `answer`, `citations`, `relevant_functions`, `relevant_types`, `confidence`, `primary_chunk_id`, `retrieved_chunks`, `assertions_passed`, `used_fallback`, `rationale`

#### Scenario: Async retrieval uses await
- **WHEN** `aforward()` executes the retrieval step
- **THEN** the `HybridRetriever.retrieve()` call SHALL use `await` instead of `asyncio.run()`

#### Scenario: Async LM generation uses await
- **WHEN** `MLXDspyLM.aforward()` generates text
- **THEN** the `MLXLLM.generate()` call SHALL use `await` instead of `asyncio.run()`

#### Scenario: Async pipeline works in pytest-asyncio
- **WHEN** a pytest-asyncio test calls `await module.acall(question=...)`
- **THEN** the pipeline SHALL complete successfully without raising `RuntimeError: Event loop is already running`

#### Scenario: Temperature and max_tokens overrides in async path
- **WHEN** `aforward()` is called with `temperature=0.7` and `max_tokens=1024`
- **THEN** the LM adapter SHALL apply those values for the generation call
- **AND** restore the original values after completion

### Requirement: Manager SHALL dispatch via async module call

The `ApiDocPipelineManager._query_dspy()` method SHALL use `await module.acall(...)` instead of `asyncio.to_thread(module, ...)` when DSPy is enabled.

#### Scenario: Manager calls acall instead of to_thread
- **WHEN** `_query_dspy()` executes a DSPy query
- **THEN** it SHALL call `await module.acall(question=query_text, ...)` on the current event loop
- **AND** NOT use `asyncio.to_thread()`

#### Scenario: Fallback on acall failure
- **WHEN** `module.acall()` raises an exception
- **THEN** `_query_dspy()` SHALL catch the exception, log a warning, and fall through to `_query_fallback()`
- **AND** the fallback response SHALL include the latency from the failed DSPy attempt
