# Test Singleton Isolation

## Purpose

Isolate global singleton state in warmup tests by resetting `_embedder_instance` before each test and restoring it afterward, preventing cross-test contamination while preserving the session-scoped seeding state for subsequent tests.

## Requirements

### Requirement: Warmup tests reset global singletons before each test

The system SHALL provide a function-scoped `isolate_global_state` fixture in warmup test files (`tests/integration/test_dspy_warmup.py`, `tests/integration/test_embedder_warmup.py`) that resets `_embedder_instance` before each test executes. The fixture SHALL be `autouse=True` so all tests in the file are automatically isolated. The fixture SHALL save the current singleton state before the test and restore it after the test completes, preserving the session-scoped seeding state for subsequent tests.

The following global SHALL be reset:
- `src.domain.services.embedding._embedder_instance` — set to `None`

#### Scenario: Embedder instance is reset before warmup test
- **WHEN** a warmup test in `test_embedder_warmup.py` starts
- **THEN** `_embedder_instance` SHALL be `None` at test start (even if a prior test set it)

#### Scenario: State is restored after warmup test
- **WHEN** a warmup test completes
- **THEN** the saved singleton state SHALL be restored
- **AND** subsequent tests SHALL see the session-scoped seeding state
