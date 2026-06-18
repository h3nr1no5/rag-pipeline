## Context

4 link-related test files exist in the project but test features that are not yet fully implemented (link resolution, link traversal, link-aware RAG). Currently these files:

- Are collected and run by pytest, producing failures or noisy output
- Trigger mypy errors, especially `test_link_resolution.py` which has 3 `# type: ignore[arg-type]` suppressions for intentionally passing `None` to test error handling
- Create a misleading impression that link features are tested and stable

The project's `pyproject.toml` already has `[[tool.mypy.overrides]]` sections for ignoring third-party modules (`jose.*`, `llama_index`, `yaml.*`, `fitz.*`), establishing a pattern for targeted mypy suppression.

## Goals / Non-Goals

**Goals:**
- Skip all 4 link-related test files during `pytest` runs with a clear "NOT IMPLEMENTED" reason
- Suppress mypy errors from all `test_link_*` files cleanly
- Minimal diff — the smallest possible set of changes to achieve the goal
- Easy to reverse when link features are ready for testing

**Non-Goals:**
- Removing or refactoring the existing test code (files stay intact)
- Changing production code in any way
- Creating new test infrastructure
- Removing existing `# type: ignore` comments from test files

## Decisions

### 1. pytest skip mechanism: module-level `pytestmark`

**Decision:** Use `pytestmark = pytest.mark.skip(reason="NOT IMPLEMENTED")` at the top of each file.

**Alternatives considered:**
- **Custom marker (`@pytest.mark.notimplemented`)** — more semantically clear but requires marking each class/function individually (more diff, more noise)
- **conftest `collect_ignore`** — centralized but non-obvious, magic behavior
- **`@pytest.mark.skipif(True, ...)`** — equivalent but unnecessarily complex

Module-level `pytestmark` is chosen because it's the idiomatic pytest approach for skipping an entire file: one line, clear intent, easy to find and remove later.

### 2. mypy exclusion: glob-based `[[tool.mypy.overrides]]`

**Decision:** Add a single override entry matching all `test_link_*` files:

```toml
[[tool.mypy.overrides]]
module = ["tests.*.test_link_*"]
ignore_errors = true
```

**Alternatives considered:**
- **Per-file overrides** (separate entry for each of 4 files) — more explicit but more verbose
- **`exclude` pattern in `[tool.mypy]`** — also works but mixes concerns (exclude != override)
- **No mypy changes** (keep status quo with 3 `# type: ignore`) — doesn't address the noise

The glob pattern is chosen because:
- It catches all current and future `test_link_*` files
- It follows the existing pattern in `pyproject.toml` (see `llama_index` and `llama_index.*` entries)
- `ignore_errors = true` silences all errors within matched files while still allowing mypy to see their module signatures if imported elsewhere

### 3. Not removing `# type: ignore` comments

**Decision:** Leave the 3 `# type: ignore[arg-type]` comments in `test_link_resolution.py` as-is. They become inert once the file is mypy-ignored via the override.

**Rationale:** Removing them would add unnecessary churn to the diff. If someone later removes the mypy override (when link features are ready), the type errors would reappear and remind them to address the suppressions properly.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **Tests become stale** — skipped tests rot while the codebase evolves | The NOT IMPLEMENTED marker is designed to be temporary; when link features are complete, re-enabling tests is a natural task |
| **Glob too broad** — a future `test_link_*` file outside the link domain could be accidentally ignored | Naming convention is specific enough (`test_link_`) that this is unlikely |
| **Forgetting to un-skip** — the NOT IMPLEMENTED markers become permanent | The `skip` reason text is searchable: `git grep "NOT IMPLEMENTED"` will find all skipped files |
| **`ignore_errors = true` hides real errors** — if someone edits these files, mypy won't catch mistakes | Acceptable trade-off: the files are skipped from CI runs anyway; errors would be caught when the skip is eventually removed |
