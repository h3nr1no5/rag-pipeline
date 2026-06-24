## Context

The rag-pipeline project has 1267 tests across 78 files (24 unit, 33 integration, 15 pdf-semantic-chunking, 1 evaluation, 5 conftest). Running `pytest --collect-only` takes 8.5s. Tests are run via `uv run pytest` directly — no wrapper, no change detection, no caching.

During OpenCode multi-agent orchestration, the coordinator delegates to @subagents/tester which runs the full suite regardless of whether relevant files changed. With 14 specialized subagents, redundant test runs accumulate significant orchestration overhead.

The project has no CI/CD pipeline, no pre-commit hooks, and no Makefile. It uses `uv` as the universal command runner with a `.venv` at the repo root.

## Goals / Non-Goals

**Goals:**
- Skip test execution entirely when no relevant source/test/config files have changed
- When changes ARE detected, run only the subset of tests affected by those changes
- Zero false negatives — no test that *should* run is ever skipped
- Automatic dependency tracking — no manually maintained mapping files
- Fast path completes in under 100ms when nothing changed
- All agents use the new pipeline by default
- `uv run pytest` still works directly for developers who want the full suite

**Non-Goals:**
- Function-level test granularity (file-level is sufficient)
- CI/CD pipeline creation (out of scope)
- Pre-commit hooks (out of scope)
- Test parallelization (already handled by pytest-xdist considerations)
- Cross-repository test selection (single repo only)

## Decisions

### Decision 1: Hybrid approach — pytest-testmon + static import analysis

| Component | Role | Trade-off |
|---|---|---|
| **pytest-testmon** | Fast everyday selection via runtime tracing | Function-level granularity, but may miss new/refactored import paths |
| **Static import analysis** | Deterministic safety net via AST parsing | File-level granularity, slower but always correct |
| **Union of both** | Eliminates false negatives | Conservative — may run extra tests, never skips required ones |

The static analysis parses all Python files in `src/` and `tests/` for `import` and `from ... import` statements using `ast.parse`, builds a file-level dependency graph, computes transitive closure, and produces a reverse index (source file → test files that depend on it). This graph is cached in `.opencode/test-deps.json` and rebuilt only when files are added/deleted.

testmon alone was rejected due to staleness (it only knows about code paths *executed during the learning run*, not all *importable* paths). The static analysis fills this gap deterministically.

**Alternatives considered:**
- *Manual YAML mapping* — rejected: reviewer flagged it as brittle with guaranteed rot
- *testmon alone* — rejected: staleness leads to silent false negatives
- *Convention-only (basename matching)* — rejected: ~20% of files have non-trivial naming patterns (B, D, E)
- *Git-only (run everything on any change)* — rejected: doesn't solve the core problem

### Decision 2: Python for the selector script, bash for the runner wrapper

`scripts/select_tests.py` is in Python (the project language, AST library available, testable). `scripts/run_tests.sh` is a thin bash wrapper that:
1. Checks `git status --porcelain` for working tree changes (fast path)
2. Delegates to `select_tests.py` for mapping changed files → test files
3. Runs the resulting test set via `uv run pytest`

No cache file for fast path — uses `git status --porcelain` directly (eliminates the race condition from the original proposed `.git/test-state` file).

### Decision 3: Conftest hierarchy handled explicitly

Conftest files don't appear in import statements (pytest injects them implicitly). The static analysis handles this by:
1. Discovering all conftest.py files and their directory scope
2. Mapping each conftest to all test files in its subtree
3. If a conftest changes, ALL tests in its scope are included

This is conservative but deterministic.

### Decision 4: Global triggers for configuration changes

Certain files affect all tests and trigger full suite when changed:

```python
GLOBAL_TRIGGERS = [
    "pyproject.toml",
    ".env.example",
    "src/core/config.py",
    "tests/conftest.py",
]
```

Changes to these files bypass the selection logic entirely and run the full suite.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|---|---|---|
| Static analysis is over-inclusive (imports guarded by `if TYPE_CHECKING`) | Runs more tests than strictly necessary | Conservative by design — extra tests are acceptable, missing tests are not |
| testmon + static analysis both need to agree on "clean" | Double runtime on first analysis build | Cache the dependency graph; rebuild only on structural changes |
| New Python file added but dependency graph stale | Graph misses new file's imports | Script checks file count/mtime against cache; triggers rebuild if mismatched |
| Agent ignores instructions and runs raw `uv run pytest` | Full suite runs despite change detection | Acceptable — developer intent. Only *automated* runs (via `/test` command and tester agent) are affected |
| Dependency graph computation is slow (>5s) | Slows first-run after structural changes | Acceptable — cached until files are added/deleted; amortized over many runs |

## Open Questions

- Should the static analysis include `conftest.py` files from `tests/unit/` and `tests/integration/` separately, or is a single `tests/conftest.py` global trigger sufficient? Current design: explicit hierarchy mapping for all conftest files.
- Should `uv add pytest-testmon` be part of this change or a separate setup step? Current design: included in the change as a dependency addition.
