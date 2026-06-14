## Why

The project's developer toolchain (mypy, ruff) runs with minimal or no configuration, catching few issues and providing weak guardrails. The dependency list also carries dead weight (`sseclient`) and a duplicate dev-dependency declaration from an incomplete uv migration. Without proper configuration, type errors and code quality issues silently accumulate.

## What Changes

- **Remove orphan `sseclient` dependency** — declared but never imported anywhere in `src/`, `client/`, or `tests/`. FastAPI's `StreamingResponse` handles SSE directly.
- **Remove duplicate `[project.optional-dependencies] dev` group** — a PEP 735 `[dependency-groups] dev` section already exists with identical contents from the uv migration. The legacy group is dead code.
- **Add `src/__init__.py`** — resolves 28/29 mypy errors (all `import-not-found` from missing package root) and the duplicate-module error in `session.py`.
- **Add `[tool.mypy]` section** to `pyproject.toml` — sets `python_version`, enables useful warnings (`warn_unused_ignores`, `warn_redundant_casts`, `implicit_optional`, `strict_equality`), and adds override rules for the 3 directly-imported packages that lack stubs (`jose`, `llama_index`, `llama_index.embeddings.huggingface`).
- **Add `[tool.ruff] select` rules** to `pyproject.toml` — extends beyond the minimal default set (F, E, W) to include import sorting (I), naming conventions (N), pyupgrade (UP), and ruff-specific rules (RUF). Adds `per-file-ignores` for tests (`S101` for `assert`).

## Capabilities

### New Capabilities

None. This change is purely developer-infrastructure / project configuration cleanup — no new user-facing or system capabilities are introduced.

### Modified Capabilities

None. No existing spec requirements change — all changes are implementation details (build config, type checking, linting).

## Impact

- **`pyproject.toml`**: Removed `sseclient` dependency; removed `[project.optional-dependencies] dev` group; added `[tool.mypy]` and `[tool.ruff]` sections
- **New file**: `src/__init__.py` (empty, package marker)
- **Developer workflow**: Mypy will now pass cleanly (0 errors); ruff will flag ~100+ additional issues (import ordering, naming, outdated syntax)
- **CI readiness**: Configuration is CI-compatible — runner can execute `uv run mypy src/` and `uv run ruff check .` with no additional setup
