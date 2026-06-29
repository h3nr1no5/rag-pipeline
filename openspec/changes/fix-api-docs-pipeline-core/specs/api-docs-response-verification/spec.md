# API Docs Response Verification

## Purpose

Post-generation claim verification against source chunks for the API documentation query pipeline, ensuring LLM-generated responses about COM interfaces, methods, properties, and types are factually grounded in the retrieved API docs context before delivery to the user.

## ADDED Requirements

### Requirement: Verify API docs answers against source chunks

The API docs query pipeline SHALL verify LLM-generated answers against their source chunks after generation and before returning to the user, using the shared `ResponseVerifier` module from the general pipeline.

#### Scenario: Answer verified successfully
- **WHEN** the LLM generates an answer for an API docs query
- **THEN** the `ResponseVerifier` SHALL check each sentence against the source chunks using the cross-encoder
- **WHEN** all sentences pass the verification threshold
- **THEN** the verified answer SHALL be returned to the user unchanged

#### Scenario: Unsupported sentences removed
- **WHEN** one or more sentences in the generated answer fail to meet the similarity threshold against any source chunk
- **THEN** those sentences SHALL be removed from the verified response (when `verification_remove_unsupported` is True)
- **THEN** the removed sentences SHALL be recorded in the response metadata as `unsupported_sentences`

#### Scenario: All sentences removed
- **WHEN** every sentence in the generated answer fails verification against the source chunks
- **THEN** the system SHALL return the fallback message: "I don't have enough information to answer this question."
- **THEN** the response SHALL have an empty `unsupported_sentences` list (all sentences were unsupported but the fallback replaces them)

#### Scenario: Verification disabled
- **WHEN** `settings.verification_enabled` is set to `False`
- **THEN** the API docs pipeline SHALL skip verification and return the raw LLM response directly

### Requirement: Use shared ResponseVerifier configuration

The API docs pipeline SHALL reuse the same `ResponseVerifier` instance and configuration (`verification_similarity_threshold`, `verification_remove_unsupported`, `verification_enabled`) from `src.core.config.settings` that the general pipeline uses.

#### Scenario: Threshold applied consistently
- **WHEN** the API docs pipeline calls `ResponseVerifier.verify()`
- **THEN** it SHALL pass the `similarity_threshold` from `settings.verification_similarity_threshold` (default `0.55`)
- **THEN** the same threshold SHALL apply to both the general pipeline and the API docs pipeline

#### Scenario: Removal policy applied consistently
- **WHEN** the API docs pipeline calls `ResponseVerifier.verify()`
- **THEN** it SHALL respect `settings.verification_remove_unsupported` for whether to remove failing sentences
- **THEN** the same removal policy SHALL apply to both pipelines
