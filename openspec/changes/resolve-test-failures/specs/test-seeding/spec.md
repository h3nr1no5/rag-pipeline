## ADDED Requirements

### Requirement: prewarm_models seeds actual model singletons

The `prewarm_models` fixture in `tests/integration/conftest.py` SHALL seed the actual model singleton instances so `get_embedder()` returns immediately without blocking. The fixture SHALL be session-scoped and autouse.

The following module-level singletons SHALL be set:
- `src.domain.services.embedding._embedder_instance` ← `TestEmbedder()`
- `src.domain.services.embedding._embedder_load_time` ← `0`
- LLM singleton ← `TestLLM()` (if applicable based on LLM module structure)

#### Scenario: Embedder singleton seeded after fixture
- **WHEN** the `prewarm_models` fixture completes
- **THEN** `embedding._embedder_instance` SHALL NOT be `None`
- **AND** `get_embedder()` SHALL return the seeded instance immediately without loading any model
- **AND** `get_embedder_stats()` SHALL reflect the seeded state

#### Scenario: Document processing completes in milliseconds
- **WHEN** a test uploads a document
- **AND** background processing calls `get_embedder()`
- **THEN** the call SHALL return immediately (no blocking)
- **AND** document processing SHALL reach "completed" status within 5 seconds

#### Scenario: Seeded embedder produces valid embeddings
- **WHEN** document processing uses the seeded `TestEmbedder` to create chunk embeddings
- **THEN** each chunk SHALL have a valid embedding (list of floats, dimension 768)
- **AND** `validate_embedding()` SHALL pass for each chunk embedding

### Requirement: prewarm_models completes in under 100ms

The `prewarm_models` fixture SHALL complete quickly. Seeding the test doubles SHALL involve creating lightweight in-memory objects, not loading real models. The entire fixture SHALL complete in under 100ms to avoid increasing test session startup time.

#### Scenario: Fixture timing
- **WHEN** the test session starts
- **THEN** the `prewarm_models` fixture SHALL complete within 100ms
- **AND** no model downloads, file I/O, or network requests SHALL occur
