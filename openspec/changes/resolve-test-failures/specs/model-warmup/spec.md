## ADDED Requirements

### Requirement: Integration test fixture seeds actual model singletons

The `prewarm_models` fixture in `tests/integration/conftest.py` SHALL seed actual model singletons (`_embedder_instance`, LLM singleton) so the full model pipeline works without blocking during tests. This extends the fixture's observable effect from "model readiness gate passes" (WarmupState is reverted) to "model pipeline works without blocking." No production warmup behavior changes.

#### Scenario: Fixture seeds embedder singleton
- **WHEN** the `prewarm_models` fixture completes
- **THEN** `embedding._embedder_instance` SHALL be a `TestEmbedder` instance
- **AND** subsequent `get_embedder()` calls SHALL return immediately without model loading

#### Scenario: Fixture seeds LLM singleton
- **WHEN** the `prewarm_models` fixture completes
- **THEN** the LLM singleton SHALL be a `TestLLM` instance
- **AND** subsequent LLM calls in tests SHALL return the canned response without model loading

#### Scenario: Production warmup behavior unchanged
- **WHEN** the server starts in production mode
- **THEN** the real model warmup (`warmup_models()`) SHALL execute as before
- **AND** no test-only code SHALL execute during production startup
