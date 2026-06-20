## ADDED Requirements

### Requirement: Post-generation claim verification

The system SHALL verify each sentence in the generated response against the source chunks after generation completes. The verification SHALL use embedding cosine similarity: each sentence is embedded and compared against all source chunk embeddings. Sentences with similarity below a configurable threshold SHALL be removed from the response (or flagged, depending on configuration).

#### Scenario: Supported claim passes verification

- **WHEN** a sentence in the response has cosine similarity ≥ 0.65 to at least one source chunk
- **THEN** the sentence SHALL be kept in the final response

#### Scenario: Unsupported claim removed

- **WHEN** a sentence in the response has cosine similarity < 0.65 to all source chunks AND `VERIFICATION_REMOVE_UNSUPPORTED` is `True`
- **THEN** the sentence SHALL be removed from the response

#### Scenario: Unsupported claim flagged

- **WHEN** a sentence in the response has cosine similarity < 0.65 to all source chunks AND `VERIFICATION_REMOVE_UNSUPPORTED` is `False`
- **THEN** the sentence SHALL be kept in the response but flagged in the response metadata

### Requirement: ResponseVerifier class

The system SHALL introduce a `ResponseVerifier` class in a new file `src/domain/services/verification.py`. The class SHALL provide a `verify(response: str, sources: list) -> VerifiedResponse` method. `VerifiedResponse` SHALL be a dataclass with fields:
- `verified_text: str` — the response after verification (unsupported claims removed or original)
- `citations: list[dict]` — per-sentence citation mapping with source indices
- `unsupported: list[str]` — sentences that were flagged or removed
- `confidence: float` — overall confidence score between 0.0 and 1.0

#### Scenario: VerifiedResponse returned

- **WHEN** `verify()` is called with a response and source chunks
- **THEN** a `VerifiedResponse` SHALL be returned with all four fields populated

### Requirement: Verification integration in LangChain chain

The `LangChainQAChain.generate()` and `generate_stream()` methods SHALL call the `ResponseVerifier` after LLM generation and before returning the response. The verification SHALL use the same source chunks that were provided in the prompt.

#### Scenario: Verification runs on every LangChain response

- **WHEN** `LangChainQAChain.generate()` completes
- **THEN** the response SHALL be passed through `ResponseVerifier.verify()` before being returned

### Requirement: Configurable verification

The system SHALL expose three configuration settings:
- `VERIFICATION_ENABLED` (bool, default `True`) — enables/disables the verification step
- `VERIFICATION_SIMILARITY_THRESHOLD` (float, default `0.65`) — cosine similarity threshold for claim support
- `VERIFICATION_REMOVE_UNSUPPORTED` (bool, default `True`) — when True, unsupported sentences are stripped; when False, they are flagged in metadata

#### Scenario: Verification can be disabled

- **WHEN** `VERIFICATION_ENABLED` is `False`
- **THEN** the system SHALL skip the verification step and return the raw LLM response unchanged

#### Scenario: Threshold is configurable

- **WHEN** `VERIFICATION_SIMILARITY_THRESHOLD` is set to `0.8`
- **THEN** only sentences with cosine similarity ≥ 0.8 to a source chunk SHALL be kept

### Requirement: Verification handles empty response

When verification removes all sentences from a response, the system SHALL return the fallback message "I don't have enough information to answer this question" instead of an empty string.

#### Scenario: All claims removed

- **WHEN** verification removes all sentences from the response
- **THEN** the system SHALL return "I don't have enough information to answer this question."
