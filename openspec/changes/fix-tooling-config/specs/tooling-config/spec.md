## ADDED Requirements

### Requirement: Mypy passes with zero errors

The mypy configuration SHALL produce zero errors when running `uv run mypy src/`.

#### Scenario: Mypy run after configuration

- **WHEN** `uv run mypy src/` is executed
- **THEN** the exit code SHALL be 0
- **THEN** no `import-not-found` errors SHALL appear (all relative imports resolve correctly)

### Requirement: Ruff checks pass

The ruff configuration SHALL pass with an agreed rule set when running `uv run ruff check .`.

#### Scenario: Ruff run after configuration

- **WHEN** `uv run ruff check .` is executed
- **THEN** no errors from configured rule sets (F, E, W, I, N, UP, RUF) SHALL appear in `src/` files
- **THEN** test files SHALL be exempt from `S101` (assert allowed in tests)

### Requirement: No orphan dependencies

Every declared dependency in `pyproject.toml` SHALL be imported by at least one file in `src/`, `client/`, or `tests/`.

#### Scenario: Dependency removal

- **WHEN** `uv run pip list` shows installed packages
- **THEN** `sseclient` SHALL NOT be listed
- **WHEN** grep for `sseclient` across the entire codebase
- **THEN** no import or reference to `sseclient` SHALL be found

### Requirement: Single dev dependency group

The project SHALL declare dev dependencies in exactly one location.

#### Scenario: No duplicate dev groups

- **WHEN** `pyproject.toml` is parsed
- **THEN** `[project.optional-dependencies] dev` SHALL NOT exist
- **THEN** `[dependency-groups] dev` SHALL exist and contain the dev dependencies

### Requirement: Package root marker exists

The `src/` directory SHALL contain a package marker file so Python tooling resolves it as a package.

#### Scenario: __init__.py presence

- **WHEN** the file `src/__init__.py` is checked
- **THEN** it SHALL exist
- **THEN** it MAY be empty
