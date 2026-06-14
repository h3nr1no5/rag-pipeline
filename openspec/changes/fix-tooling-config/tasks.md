## 1. Dependency Cleanup

- [ ] 1.1 Remove `sseclient` from `[project] dependencies` in `pyproject.toml`
- [ ] 1.2 Remove `[project.optional-dependencies] dev` section (duplicate of `[dependency-groups] dev`)
- [ ] 1.3 Run `uv sync` to update lock file and verify removal

## 2. Package Root Fix

- [ ] 2.1 Create `src/__init__.py` (empty file, package marker)

## 3. Mypy Configuration

- [ ] 3.1 Add `[tool.mypy]` section to `pyproject.toml` with `python_version`, `warn_unused_ignores`, `warn_redundant_casts`, `pretty`, `show_error_codes`, `implicit_optional`, `strict_equality`
- [ ] 3.2 Add override rules for `jose.*`, `llama_index`, `llama_index.*`, `llama_index.embeddings.huggingface.*` with `ignore_missing_imports = true`
- [ ] 3.3 Run `uv run mypy src/` and verify zero errors (exit code 0)

## 4. Ruff Configuration

- [ ] 4.1 Add `select` and `per-file-ignores` to `[tool.ruff]` in `pyproject.toml` with rules: F, E, W, I, N, UP, RUF; per-file-ignores: `tests/**` for S101
- [ ] 4.2 Run `uv run ruff check .` and verify all errors are resolved (exit code 0)
- [ ] 4.3 Run `uv run ruff format --check .` for baseline awareness

## 5. Verification

- [ ] 5.1 Confirm `uv run pytest -v` passes with no regressions
- [ ] 5.2 Confirm `uv run ruff check .` passes cleanly
- [ ] 5.3 Confirm `uv run mypy src/` passes with zero errors
