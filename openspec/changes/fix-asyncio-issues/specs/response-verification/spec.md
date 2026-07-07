# Response Verification — Delta Spec

## MODIFIED Requirements

### Requirement: Cross-encoder scoring SHALL batch all sentence-source pairs

The `ResponseVerifier.verify()` method SHALL collect all (sentence, source_text) pairs into a single cross-encoder `model.predict()` call, instead of calling `_score_with_cross_encoder()` once per sentence.

**Rationale**: Each call to `model.predict()` has fixed per-call overhead. For a response with 10 sentences and 10 sources, the current code makes 10 separate `predict()` calls. Batching all 100 pairs into a single call reduces overhead and improves verification throughput.

#### Scenario: All pairs scored in single predict call
- **WHEN** `verify()` processes a response with N sentences and M source texts
- **THEN** the system SHALL construct N × M (sentence, source) pairs
- **AND** SHALL call `model.predict()` exactly once with all pairs
- **AND** SHALL split the results back per-sentence for citation matching

#### Scenario: Empty response produces no predict call
- **WHEN** the response text contains no sentences (empty or whitespace-only)
- **THEN** `verify()` SHALL return the response unchanged with confidence 1.0
- **AND** SHALL NOT call `model.predict()` at all
