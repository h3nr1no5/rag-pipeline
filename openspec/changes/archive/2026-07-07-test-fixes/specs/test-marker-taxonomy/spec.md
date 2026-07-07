# Test Marker Taxonomy

## Purpose

Define and register a set of custom pytest markers for classifying tests by level, speed, stability, and dependency. Markers enable targeted test selection via `pytest -m` expressions.

## ADDED Requirements

### Requirement: Markers SHALL be registered in pyproject.toml

The system SHALL register the following custom markers under `[tool.pytest.ini_options]` in `pyproject.toml`:

```toml
markers = [
    "unit: Pure logic tests, no I/O or database",
    "integration: Tests requiring database or service layer",
    "e2e: Full application bootstrap tests (subprocess server)",
    "fast: Completes in under 0.5s",
    "slow: Takes 0.5s or longer (often LLM-dependent)",
    "flaky: Known to be intermittently unreliable",
    "needs_llm: Requires LLM model to be loaded",
    "needs_db: Requires database connection",
    "needs_disk: Requires file I/O (uploads, PDFs)",
]
```

#### Scenario: Markers are registered
- **WHEN** `uv run pytest --markers` is executed
- **THEN** the output SHALL include all registered markers with their descriptions
- **THEN** `unit`, `integration`, `e2e`, `fast`, `slow`, `flaky`, `needs_llm`, `needs_db`, and `needs_disk` SHALL all appear

#### Scenario: Strict markers mode validates all markers
- **WHEN** `uv run pytest --strict-markers` is executed
- **AND** all tests use only registered markers
- **THEN** no `PytestUnknownMarkersWarning` SHALL be raised

### Requirement: `slow` marker SHALL be applied to `test_server_smoke.py`

The `TestServerSmoke` class in `tests/integration/test_server_smoke.py` SHALL be decorated with `@pytest.mark.slow` to indicate it launches a subprocess server (~8s setup).

#### Scenario: test_server_smoke is marked slow
- **WHEN** `uv run pytest tests/integration/test_server_smoke.py --co` is executed
- **THEN** the collected test SHALL have marker `slow`

#### Scenario: Fast CI run skips test_server_smoke
- **WHEN** `uv run pytest -m "fast"` is executed
- **THEN** `test_server_smoke.py::TestServerSmoke::test_health_endpoint` SHALL NOT be collected

### Requirement: Marker descriptions SHALL follow naming convention

Marker names SHALL use kebab-case (e.g., `needs_llm`, not `needsLLM` or `needs-llm`). Marker descriptions SHALL be present tense, explaining what the marker classifies.

#### Scenario: Marker names are consistent
- **WHEN** a new marker is added
- **THEN** its name SHALL use lowercase with underscores separating words
- **THEN** its description SHALL explain what type of test it identifies
