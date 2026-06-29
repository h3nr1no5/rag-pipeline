## ADDED Requirements

### Requirement: Pipeline SHALL propagate rationale from DSPy predictor

The `APIDocRAG.forward()` method SHALL capture `response.rationale` from the `APIResponseGenerator` ChainOfThought predictor and include it in the return dict. The `ApiDocPipelineManager._build_dspy_response()` method SHALL map this value to the `reasoning_hint` field of `ApiDocQueryResponse`.

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
