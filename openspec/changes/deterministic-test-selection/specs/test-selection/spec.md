## ADDED Requirements

### Requirement: Fast-path skip when nothing changed
When no source files, test files, or configuration files have been modified since the last commit, the test runner SHALL exit immediately without executing any tests.

#### Scenario: Clean working tree skips tests
- **WHEN** `git status --porcelain` shows no changes to `src/`, `tests/`, `pyproject.toml`, or `.env.example`
- **THEN** the runner prints "No relevant changes detected. Skipping tests." and exits with code 0

#### Scenario: Changed README.md does not trigger tests
- **WHEN** only `README.md` or other documentation files have changed
- **THEN** the runner skips tests (these files are not in the relevant change set)

### Requirement: Change-driven test selection
When relevant files have changed, the runner SHALL select only those tests that are affected by the changes, using a combination of pytest-testmon (runtime tracing) and static import analysis (AST-parsed dependency graph).

#### Scenario: Single source file changes
- **WHEN** `src/domain/services/embedding.py` has been modified
- **THEN** the runner executes `tests/unit/test_embedding.py` (mapped via import graph or testmon)

#### Scenario: Conftest file changes triggers subtree
- **WHEN** `tests/unit/conftest.py` has been modified
- **THEN** ALL tests under `tests/unit/` are executed

#### Scenario: Multiple files changed
- **WHEN** `src/domain/services/chunking.py` AND `src/domain/services/embedding.py` have changed
- **THEN** the union of all affected tests (deduplicated) is executed

### Requirement: Global trigger for configuration changes
Certain files affect ALL tests. Changes to these files SHALL trigger the full test suite.

#### Scenario: pyproject.toml changes trigger full suite
- **WHEN** `pyproject.toml` has been modified
- **THEN** the runner executes the complete test suite (all 1267 tests)

#### Scenario: Root conftest changes trigger full suite
- **WHEN** `tests/conftest.py` has been modified
- **THEN** the runner executes the complete test suite

### Requirement: Zero false negatives
The test selection mechanism SHALL never skip a test that could be affected by a change. The static import analysis acts as a deterministic safety net over testmon's runtime tracing.

#### Scenario: New import dependency discovered
- **WHEN** `src/domain/services/verification.py` is refactored to import a new module
- **THEN** the static analysis includes that new module in the dependency graph, so changes to it trigger `test_verification.py`

#### Scenario: Import graph staleness is impossible
- **WHEN** the static analysis is enabled
- **THEN** ALL import-level dependencies are captured deterministically via AST parsing, not via runtime execution tracing. No learning run is needed. No stale mappings can occur.

### Requirement: Agent adoption
The OpenCode test command and tester agent SHALL use the new test selection pipeline instead of raw `uv run pytest`.

#### Scenario: /test command uses selection
- **WHEN** a developer or agent runs the `/test` command
- **THEN** it delegates through `scripts/run_tests.sh` which performs change detection and selection

#### Scenario: Tester agent uses selection
- **WHEN** @subagents/tester is invoked to run tests
- **THEN** its instructions direct it to use `scripts/run_tests.sh` instead of `uv run pytest`

### Requirement: Manual full-suite override
Developers SHALL still be able to run the complete test suite directly.

#### Scenario: Direct pytest invocation works
- **WHEN** a developer runs `uv run pytest` directly
- **THEN** all tests execute without any change detection filtering

#### Scenario: Force flag overrides selection
- **WHEN** a developer runs `scripts/run_tests.sh --force`
- **THEN** the full test suite executes regardless of change detection
