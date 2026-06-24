## 1. Setup

- [ ] 1.1 Add `pytest-testmon` to the `dev` dependency group in `pyproject.toml`
- [ ] 1.2 Run `uv sync` to install the new dependency

## 2. Static Import Analysis Engine

- [ ] 2.1 Create `scripts/select_tests.py` with AST-based import parser that walks `src/` and `tests/` and extracts all `import` / `from ... import` statements
- [ ] 2.2 Implement dependency graph builder: resolve imports to concrete file paths, compute transitive closure for each test file
- [ ] 2.3 Implement conftest hierarchy discovery: map each conftest.py to all test files in its directory subtree
- [ ] 2.4 Implement graph caching to `.opencode/test-deps.json` with invalidation on file add/delete
- [ ] 2.5 Implement change detection via `git diff --name-only HEAD` against `src/`, `tests/`, `pyproject.toml`, `.env.example`
- [ ] 2.6 Implement global trigger detection: changes to `pyproject.toml`, `tests/conftest.py` etc. return full suite
- [ ] 2.7 Implement reverse index lookup: changed file → affected test files via dependency graph
- [ ] 2.8 Add `--dry-run` flag: print what would run without executing tests
- [ ] 2.9 Add `--list-orphans` flag: show test files not reachable from any source file in the graph

## 3. Runner Wrapper

- [ ] 3.1 Create `scripts/run_tests.sh` with fast-path check (`git status --porcelain` for changes to relevant paths)
- [ ] 3.2 Implement delegation to `scripts/select_tests.py` for change → test mapping
- [ ] 3.3 Implement `--force` flag to bypass change detection and run full suite
- [ ] 3.4 Implement `--unit`, `--integration`, `--all` flags for explicit scope selection
- [ ] 3.5 Implement testmon integration: run `uv run pytest --testmon` on the selected test set
- [ ] 3.6 Implement static analysis fallback: if testmon returns empty, use the static analysis result as the safety net
- [ ] 3.7 Ensure proper exit codes (0 for skip/pass, non-zero for failures)

## 4. OpenCode Integration

- [ ] 4.1 Update `.opencode/commands/test.md` to delegate through `scripts/run_tests.sh`
- [ ] 4.2 Update `.opencode/agents/subagents/tester.md` instructions to use `scripts/run_tests.sh` instead of raw `uv run pytest`
- [ ] 4.3 Update `AGENTS.md` quick commands section — replace `uv run pytest` lines with `scripts/run_tests.sh` equivalents

## 5. Verification

- [ ] 5.1 Run `scripts/run_tests.sh` on clean working tree — verify it skips with "No relevant changes detected"
- [ ] 5.2 Modify a source file, run `scripts/run_tests.sh` — verify only affected tests run
- [ ] 5.3 Modify `pyproject.toml`, run `scripts/run_tests.sh` — verify full suite runs
- [ ] 5.4 Run `scripts/run_tests.sh --force` — verify full suite runs regardless of changes
- [ ] 5.5 Run `scripts/select_tests.py --dry-run` — verify output matches expectations
- [ ] 5.6 Run full suite via `uv run pytest` — verify manual path still works unchanged
