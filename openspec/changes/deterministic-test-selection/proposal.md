## Why

During multi-agent orchestration, each subagent independently runs tests via `uv run pytest`. With 1267 tests across 78 files (8.5s just to collect), this is extremely wasteful when nothing relevant has changed. There is no mechanism to select only affected tests or skip testing entirely when source/test files are unchanged.

## What Changes

- **New `scripts/run_tests.sh`** — entry point for all test execution during orchestration; performs change detection and routes to the right test subset
- **New `scripts/select_tests.py`** — deterministic test selector that combines pytest-testmon (runtime tracing) with static import analysis (AST-parsed dependency graph) for zero-staleness coverage
- **New `.opencode/test-deps.json`** — cached static dependency graph (auto-generated, not manually maintained)
- **Modified `.opencode/commands/test.md`** — updated to delegate through the new pipeline instead of raw `uv run pytest`
- **Modified `.opencode/agents/subagents/tester.md`** — updated instructions to use `scripts/run_tests.sh`
- **Modified `AGENTS.md`** — quick commands updated to use the new test runner
- **New dependency**: `pytest-testmon` added to dev dependency group

## Capabilities

### New Capabilities
- `test-selection`: Deterministic selection of affected tests based on file changes. Combines pytest-testmon (fast, function-level) with static import analysis (complete, file-level) for zero false negatives. Handles conftest.py hierarchy, global triggers (pyproject.toml), and provides fast-path skip when nothing changed.

### Modified Capabilities
- *(No existing specs change at the requirements level. Existing test specs — `test-isolation`, `test-performance`, `test-flaky-determinism`, `test-infra-consolidation` — are unaffected.)*

## Impact

- **New files**: `scripts/run_tests.sh`, `scripts/select_tests.py`, `.opencode/test-deps.json`
- **Modified files**: `.opencode/commands/test.md`, `.opencode/agents/subagents/tester.md`, `AGENTS.md`, `pyproject.toml` (add dev dep)
- **Behavior change**: `uv run pytest` is no longer the primary test command for agents — they use `scripts/run_tests.sh` instead, which may skip or subset tests based on change detection
- **No breaking changes**: `uv run pytest` still works directly for developers who want to run the full suite
