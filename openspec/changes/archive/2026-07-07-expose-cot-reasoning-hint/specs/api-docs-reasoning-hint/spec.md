## ADDED Requirements

### Requirement: API docs query response SHALL include reasoning_hint field

The `ApiDocQueryResponse` model SHALL include an optional `reasoning_hint: str` field that contains the raw ChainOfThought rationale from the `APIResponseGenerator` DSPy predictor. When the non-DSPy fallback path is used, the field SHALL be an empty string.

#### Scenario: DSPy path returns non-empty reasoning_hint
- **WHEN** a query is processed through the DSPy pipeline
- **AND** the `APIResponseGenerator` (ChainOfThought) produces a response
- **THEN** the response SHALL include a `reasoning_hint` field with the raw rationale text
- **AND** the field SHALL contain the DSPy `response.rationale` value

#### Scenario: Fallback path returns empty reasoning_hint
- **WHEN** a query is processed through the fallback `_generate_answer()` path (DSPy disabled or failed)
- **THEN** the response SHALL include a `reasoning_hint` field set to `""`

#### Scenario: Cached response includes reasoning_hint
- **WHEN** a previously cached response is returned
- **THEN** the `reasoning_hint` field SHALL be included with the cached value
