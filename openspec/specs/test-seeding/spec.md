# Test Seeding

## Purpose

Seed actual model singleton instances (embedder, LLM) before the test session so `get_embedder()` and `get_llm()` return immediately without blocking, enabling fast document processing tests.

## Requirements

### Requirement: Singleton-seeding fixture seeds actual model singletons

The system SHALL provide a session-scoped autouse fixture in `tests/integration/conftest.py` that seeds the actual model singleton instances so `get_embedder()` returns immediately without blocking.

The following module-level singletons SHALL be set:
- `src.domain.services.embedding._embedder_instance` ← `TestEmbedder()`
- `src.domain.services.embedding._embedder_load_time` ← `0`
- LLM singleton ← `TestLLM()`

#### Scenario: Embedder singleton seeded after fixture
- **WHEN** the fixture completes
- **THEN** `embedding._embedder_instance` SHALL NOT be `None`
- **AND** `get_embedder()` SHALL return the seeded instance immediately without loading any model

#### Scenario: Document processing completes in milliseconds
- **WHEN** a test uploads a document
- **AND** background processing calls `get_embedder()`
- **THEN** the call SHALL return immediately (no blocking)
- **AND** document processing SHALL reach "completed" status within 5 seconds

#### Scenario: Seeded embedder produces valid embeddings
- **WHEN** document processing uses the seeded `TestEmbedder` to create chunk embeddings
- **THEN** each chunk SHALL have a valid embedding (list of floats, dimension 768)
- **AND** `validate_embedding()` SHALL pass for each chunk embedding

### Requirement: Fixture completes in under 100ms

The fixture SHALL complete quickly. Seeding the test doubles SHALL involve creating lightweight in-memory objects, not loading real models. The entire fixture SHALL complete in under 100ms to avoid increasing test session startup time.

#### Scenario: Fixture timing
- **WHEN** the test session starts
- **THEN** the fixture SHALL complete within 100ms
- **AND** no model downloads, file I/O, or network requests SHALL occur
