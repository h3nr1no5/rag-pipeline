## Context

The project's `pyproject.toml` is the sole configuration file for build, test, linting, and type-checking. Currently:

- **Mypy**: No `[tool.mypy]` section exists. Mypy runs with defaults and produces 29 errors — all caused by `src/` lacking an `__init__.py` (preventing mypy from resolving it as a package root).
- **Ruff**: Only `target-version` and `line-length` configured. Default rule set (F, E, W) catches 20 errors but misses import ordering, naming conventions, and pyupgrade opportunities.
- **Dependencies**: `sseclient` is declared but never imported anywhere. A duplicate dev-dependency group (`[project.optional-dependencies] dev`) mirrors the PEP 735 `[dependency-groups] dev`.
- **No CI yet**: Config changes are designed to be CI-ready but CI itself is deferred to a separate change.

## Goals / Non-Goals

**Goals:**
- Remove dead/invalid dependency declarations from `pyproject.toml`
- Add `src/__init__.py` so mypy resolves the project as a proper package
- Configure mypy to catch real type issues without noise (0 errors after config)
- Expand ruff rule coverage to catch import ordering, naming, and modernization issues
- Keep all changes confined to `pyproject.toml` and `src/__init__.py` — no application code changes

**Non-Goals:**
- Adding CI/CD pipelines (deferred to separate change)
- Fixing pre-existing type errors in application code (mypy will run cleanly after config; deeper type coverage is a future effort)
- Adding Docker configuration
- Changing application behavior or API surface

## Decisions

### Decision 1: `src/__init__.py` over `--explicit-package-bases`

Adding an empty `src/__init__.py` is the standard Python packaging convention and resolves both the 28 `import-not-found` errors and the duplicate-module error in `session.py`. The alternative (`--explicit-package-bases` CLI flag) addresses import resolution but does not fix the duplicate-module error.

### Decision 2: Conservative mypy rule selection

The selected rules (`warn_unused_ignores`, `warn_redundant_casts`, `implicit_optional`, `strict_equality`) provide high-value warnings with near-zero noise. Deliberately excluded at this stage:
- `disallow_untyped_defs` (would fire on ~200+ untyped functions)
- `warn_return_any` (codebase uses `dict[str, Any]` for JWT payloads — legitimate)
- `strict` mode (would require extensive annotation additions)

Override rules cover only the 3 directly-imported packages lacking stubs: `jose`, `llama_index`, `llama_index.embeddings.huggingface`. All other dependencies (38 packages) ship `py.typed` and type-check fine.

### Decision 3: Moderate ruff rule expansion, not --select ALL

Running `--select ALL` produces 7,406 errors — overwhelming for an existing codebase. Instead, the phased approach starts with:
- **Phase 1 (this change)**: F, E, W, I, N, UP, RUF — catches import ordering, naming, and modernization without being noisy
- **Per-file-ignores**: `S101` (assert) allowed in tests; `INP001` (implicit-namespace-package) allowed for `src/`

Future phases can add B, SIM, C4, RET, G for deeper linting.

### Decision 4: Remove `sseclient`, keep `sse-starlette` out

`sseclient` was intended as `sse-starlette` but the application doesn't use SSE library features — FastAPI's built-in `StreamingResponse` with `media_type="text/event-stream"` handles the only streaming endpoint. Removing entirely rather than replacing reduces the dependency footprint.

### Decision 5: Remove duplicate dev group, not merge

`[project.optional-dependencies]` is the legacy PEP 621 location. `[dependency-groups]` (PEP 735) is the modern uv standard. Keeping only the new group avoids confusion and is forward-compatible.

## Risks / Trade-offs

- **[Low] Mypy stricter than before**: Developers adding types will need to satisfy `strict_equality` and `implicit_optional`. Mitigation: these are sensible rules that prevent real bugs; any friction is short-term.
- **[Low] Ruff import sorting may conflict with team habits**: `I` (isort) will flag unsorted imports. Mitigation: `ruff format` auto-fixes this; a single `ruff check --fix` run resolves everything.
- **[None] No application behavior change**: All changes are build configuration only. Zero risk of runtime regressions.
