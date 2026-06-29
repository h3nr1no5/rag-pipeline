## ADDED Requirements

### Requirement: API-docs answer generation produces detailed reasoning answers

The `APIResponseGenerator` DSPy signature SHALL produce an `answer` output field that contains a detailed, step-by-step analysis including inline reasoning, not just a concise final answer. The answer SHALL walk through the user's question, identify relevant functions and types from context, explain their usage, and provide the final conclusion — all with inline `[FunctionName]` citations where applicable.

#### Scenario: DSPy generates detailed CoT-style answer

- **WHEN** the user asks a question about an API function documented in the context
- **THEN** the `answer` field SHALL contain a multi-sentence explanation that includes reasoning steps, references to specific functions/types, and the final conclusion
- **THEN** the answer SHALL be grounded in the provided context and not introduce external information

#### Scenario: Answer contains inline citations

- **WHEN** the DSPy pipeline generates an answer
- **THEN** the answer MAY include `[FunctionName]` inline citations referencing functions or types present in the context
- **THEN** the answer SHALL NOT be rejected or retried solely due to missing or malformed citation formatting

### Requirement: Citation assertions are advisory only

The DSPy citation validation (`validate_citations`) and question reference checks (`check_question_references`) SHALL log warnings with assertion details but SHALL NOT trigger fallback to `Predict` when they fail. The ChainOfThought output SHALL be accepted regardless of assertion results.

#### Scenario: Assertions fail but output is accepted

- **WHEN** the `APIResponseGenerator` (ChainOfThought) produces an answer
- **WHEN** `validate_citations()` detects missing or unknown inline citations
- **THEN** a warning SHALL be logged with the assertion details
- **THEN** the answer SHALL NOT be replaced with a `Predict` fallback
- **THEN** the original ChainOfThought answer SHALL be returned in the response
- **THEN** the response SHALL include metadata indicating assertions did not pass

#### Scenario: Assertions pass

- **WHEN** `validate_citations()` and `check_question_references()` both pass
- **THEN** the answer SHALL be returned normally
- **THEN** the response SHALL include metadata indicating assertions passed

### Requirement: Per-request verification toggle

The `ApiDocQueryRequest` SHALL accept an optional `verification_enabled` boolean field (default `true`). When `false`, the system SHALL skip the `ResponseVerifier` step entirely and return the raw DSPy-generated answer.

#### Scenario: Verification disabled

- **WHEN** a client sends `"verification_enabled": false` in the request body
- **THEN** the `ResponseVerifier` SHALL NOT be invoked for that request
- **THEN** the answer SHALL be the raw output from the DSPy pipeline (or fallback)
- **THEN** the `unsupported_sentences` field in the response SHALL be empty

#### Scenario: Verification enabled (default)

- **WHEN** a client omits `verification_enabled` or sends `"verification_enabled": true`
- **THEN** the `ResponseVerifier` SHALL be invoked as before
- **THEN** the answer SHALL be the verified text

### Requirement: Temperature override for api-docs pipeline

The api-docs pipeline SHALL use a temperature of 0.3 for LLM generation (configurable via settings). This increases the model's willingness to produce detailed, confident answers while remaining factual.

#### Scenario: Api-docs query uses higher temperature

- **WHEN** a query is processed via the api-docs endpoint
- **THEN** the LLM generation SHALL use `temperature = 0.3` (or the configured `api_docs_temperature` value)
- **THEN** this SHALL NOT affect the generic `/api/v1/query` endpoint's temperature

### Requirement: Verification threshold tuning for DSPy path

When verification is enabled on the DSPy path, sentences SHALL only be stripped if the cross-encoder score is below `verification_similarity_threshold * 0.5` (i.e., requires stronger evidence before declaring a sentence unsupported). This prevents technical API prose from being incorrectly stripped.

#### Scenario: Technical sentence passes verification

- **WHEN** a sentence from a DSPy-generated answer describes an API function or parameter
- **WHEN** the sentence has partial semantic similarity to the source context (above `threshold * 0.5`)
- **THEN** the sentence SHALL be retained in the verified answer
- **THEN** the sentence SHALL NOT appear in `unsupported_sentences`
