# Response Verification

Post-generation claim verification against source chunks for the RAG pipeline.

## ADDED Requirements

### Requirement: Configurable similarity threshold

The verification similarity threshold SHALL be configurable via `verification_similarity_threshold` with a default value of `0.55`.

#### Scenario: Default threshold applied
- **WHEN** `verify()` is called without an explicit `similarity_threshold` override
- **THEN** the system SHALL use `0.55` as the minimum cosine similarity for a sentence to be considered supported

#### Scenario: Sentence passes verification
- **WHEN** a sentence's cosine similarity to its best-matching source chunk is >= 0.55
- **THEN** the sentence SHALL be retained in the verified response

#### Scenario: Sentence fails verification
- **WHEN** a sentence's cosine similarity to all source chunks is < 0.55
- **THEN** the sentence SHALL be removed from the verified response (when `verification_remove_unsupported` is True)
- **THEN** the sentence SHALL be recorded in the `unsupported` list

#### Scenario: All sentences removed
- **WHEN** every sentence in the response fails verification
- **THEN** the system SHALL return the fallback message: "I don't have enough information to answer this question."

### Requirement: Verification can be disabled

The system SHALL support disabling verification entirely via `verification_enabled = False`.

#### Scenario: Verification disabled
- **WHEN** `verification_enabled` is False
- **THEN** the `verify()` method SHALL return the original response unchanged with confidence 1.0
- **THEN** no sentence-level analysis SHALL be performed
