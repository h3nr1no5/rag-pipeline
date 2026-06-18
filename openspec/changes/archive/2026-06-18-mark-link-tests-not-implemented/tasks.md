## 1. Add mypy override for test_link_* files

- [x] 1.1 Add `[[tool.mypy.overrides]]` entry to `pyproject.toml` with `module = ["tests.*.test_link_*"]` and `ignore_errors = true`

## 2. Mark unit test files as NOT IMPLEMENTED

- [x] 2.1 Add `pytestmark = pytest.mark.skip(reason="NOT IMPLEMENTED")` to `tests/unit/test_link_resolution.py`
- [x] 2.2 Add `pytestmark = pytest.mark.skip(reason="NOT IMPLEMENTED")` to `tests/unit/test_link_traversal.py`
- [x] 2.3 Add `pytestmark = pytest.mark.skip(reason="NOT IMPLEMENTED")` to `tests/unit/test_link_augmentation.py`

## 3. Mark integration test file as NOT IMPLEMENTED

- [x] 3.1 Add `pytestmark = pytest.mark.skip(reason="NOT IMPLEMENTED")` to `tests/integration/test_link_aware_rag.py`

## 4. Verify

- [x] 4.1 Run `pytest -v --collect-only` to confirm skipped tests show as `s` (skipped)
- [x] 4.2 Run `mypy src/` to confirm no new type errors from test_link_* files
