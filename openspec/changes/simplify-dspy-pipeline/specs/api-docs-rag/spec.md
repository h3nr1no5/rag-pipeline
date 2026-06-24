## ADDED Requirements

### Requirement: DSPy pipeline SHALL use raw question for retrieval

The `APIDocRAG.forward()` method SHALL use the user's raw question directly as the hybrid retrieval query, instead of passing it through an LLM-based QueryAnalyzer. ChainOfThought reasoning SHALL be preserved in the `APIResponseGenerator`.

**Rationale**: The Qwen 1.5B model's QueryAnalyzer frequently generates search queries that miss relevant chunks, causing downstream hallucination. The same model used without multi-step orchestration (raw question → retrieve → generate) produces correct answers.

#### Scenario: Raw question used as search query

- **WHEN** `APIDocRAG.forward()` is called with a user question
- **THEN** the question SHALL be used directly (not rewritten by QueryAnalyzer)
- **AND** hybrid retrieval SHALL execute with the raw question text

#### Scenario: All retrieved chunks passed to generator

- **WHEN** hybrid retrieval returns chunks for the raw question
- **THEN** all retrieved chunks SHALL be passed directly to the `APIResponseGenerator` (no ContextAssembler selection step)
- **AND** the ChainOfThought predictor SHALL still produce a `reasoning` output field

#### Scenario: CoT reasoning still populated

- **WHEN** the `APIResponseGenerator` (ChainOfThought) produces a response
- **THEN** the returned dict SHALL include a `"rationale"` key
- **AND** the `reasoning_hint` field in `ApiDocQueryResponse` SHALL be populated as before
