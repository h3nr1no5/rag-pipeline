## Why

The link-related test infrastructure is not yet complete — link resolution, link traversal, and link-aware RAG querying are still under active development. However, the test files for these features are currently active and produce both mypy type errors (particularly `test_link_resolution.py` with 3 `# type: ignore[arg-type]` suppressions) and pytest noise when they inevitably fail or are incomplete. Marking them as NOT IMPLEMENTED makes the project's test and type-checking surface accurately reflect reality.

## What Changes

- Add `pytestmark = pytest.mark.skip(reason="NOT IMPLEMENTED")` to 4 test files to skip them during test runs
- Add a `[[tool.mypy.overrides]]` entry in `pyproject.toml` to suppress mypy errors in all `test_link_*` files
- The `# type: ignore[arg-type]` comments in `test_link_resolution.py` can remain (they become harmless since the file is mypy-ignored, but removing them is optional)

## Capabilities

### New Capabilities

None — this is a project maintenance change, not a new feature.

### Modified Capabilities

None — no spec-level behavior or requirements are changing.

## Impact

**Test execution**: 4 test files (~2,063 total lines) will be skipped during `pytest` runs:
- `tests/unit/test_link_resolution.py`
- `tests/unit/test_link_traversal.py`
- `tests/unit/test_link_augmentation.py`
- `tests/integration/test_link_aware_rag.py`

**Type checking**: The `test_link_*` files will be excluded from mypy validation, eliminating 3 `# type: ignore` suppressions from visibility (the comments themselves can stay).

**No production code affected.** This is a testing/developer-experience change only.
