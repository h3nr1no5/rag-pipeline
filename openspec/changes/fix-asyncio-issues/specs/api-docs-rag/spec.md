# API Docs RAG — Delta Spec

## MODIFIED Requirements

### Requirement: Pipeline SHALL propagate rationale from DSPy predictor

The `APIDocRAG.forward()` method SHALL capture `response.reasoning` from the `APIResponseGenerator` ChainOfThought predictor and include it in the return dict. The `ApiDocPipelineManager._build_dspy_response()` method SHALL map this value to the `reasoning_hint` field of `ApiDocQueryResponse`.

**Modification**: The `APIDocRAG.forward()` method SHALL use `asyncio.run_coroutine_threadsafe()` instead of `asyncio.run()` for bridging sync-to-async when a running event loop is detected. The `MLXDspyLM.forward()` method SHALL use the same pattern for calling `MLXLLM.generate()`.

**Rationale**: `asyncio.run()` creates a new event loop on the current thread. When called from within a running event loop (e.g., when `manager.py` calls `module.forward()` directly instead of via `asyncio.to_thread()`), `asyncio.run()` raises `RuntimeError`. Using `asyncio.get_running_loop()` detection + `asyncio.run_coroutine_threadsafe()` correctly handles both cases.

#### Scenario: Rationale captured in pipeline output
- **WHEN** `APIDocRAG.forward()` completes the generation stage
- **THEN** the returned dict SHALL include a `"rationale"` key with the DSPy rationale value
- **AND** this value SHALL be a non-empty string when the DSPy path succeeds

#### Scenario: Rationale mapped to ApiDocQueryResponse
- **WHEN** `_build_dspy_response()` constructs the response
- **THEN** the `ApiDocQueryResponse.reasoning_hint` field SHALL be set from the `"rationale"` value

#### Scenario: Fallback path sets empty reasoning_hint
- **WHEN** `_query_fallback()` generates a response
- **THEN** the `ApiDocQueryResponse.reasoning_hint` field SHALL be an empty string

#### Scenario: Forward called from running event loop
- **WHEN** `manager._query_dspy()` calls `module.forward()` directly (not via `asyncio.to_thread()`)
- **AND** a running event loop is detected via `asyncio.get_running_loop()`
- **THEN** `_forward_impl()` SHALL use `asyncio.run_coroutine_threadsafe()` to schedule retrieval coroutine on the running loop
- **AND** SHALL block on the returned Future to obtain results
- **AND** the pipeline SHALL produce identical output to the thread-based path

#### Scenario: Forward called from thread without event loop
- **WHEN** `module.forward()` is called from a thread with no running event loop
- **THEN** `_forward_impl()` SHALL use `asyncio.run()` to execute retrieval (existing behavior, unchanged)

#### Scenario: LM adapter bridges to async LLM correctly
- **WHEN** `MLXDspyLM.forward()` is called from within a running event loop
- **THEN** it SHALL use `asyncio.run_coroutine_threadsafe()` to call `MLXLLM.generate()`
- **AND** SHALL return the generated text to DSPy synchronously
