## MODIFIED Requirements

### Requirement: Pipeline SHALL propagate rationale from DSPy predictor

The `APIDocRAG.forward()` method SHALL include a `"rationale"` key in its return dict with an empty string value, since the `Predict` predictor does not produce a `reasoning` field. The `ApiDocPipelineManager._build_dspy_response()` method SHALL map this empty value to the `reasoning_hint` field of `ApiDocQueryResponse`.

**Rationale for change**: The generation stage was simplified from `ChainOfThought` (which produced a `reasoning` field) to `Predict` (which does not). The `rationale` key is retained in the return dict for backward compatibility, but will always be an empty string.

#### Scenario: Rationale is always empty string
- **WHEN** `APIDocRAG.forward()` completes the generation stage
- **THEN** the returned dict SHALL include a `"rationale"` key with an empty string value `""`

#### Scenario: Empty rationale mapped to ApiDocQueryResponse
- **WHEN** `_build_dspy_response()` constructs the response from Predict output
- **THEN** the `ApiDocQueryResponse.reasoning_hint` field SHALL be set to an empty string
