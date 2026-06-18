## Context

Two test files in the PDF semantic chunking module (`test_assembler.py`, `test_boundaries.py`) use helper factory functions (`_make_el`, `_make_com_el`) whose parameter types are unnecessarily wide — `str` instead of the `ElementType`/`ComElementType` Literal aliases used by the models they construct. This forces mypy to reject the direct argument, requiring 9 `# type: ignore[arg-type]` annotations across the two files.

There are 134 `DocumentElement(type=...)` calls across all test files. The 9 with ignores are the only ones that go through these helper functions — every other file passes literal strings directly and mypy accepts them.

The existing imports in both files bring in `DocumentElement` and `ComDocumentElement` but not their associated type aliases (`ElementType`, `ComElementType`). Both type aliases are already exported from their respective modules.

## Goals / Non-Goals

**Goals:**
- Remove all 9 stale `# type: ignore[arg-type]` annotations from `test_assembler.py` and `test_boundaries.py`
- Narrow the 4 helper function signatures to use `ElementType`/`ComElementType` instead of `str`/`str | None`
- Pass existing mypy checks with zero new errors
- All existing tests continue to pass unchanged

**Non-Goals:**
- Changing the `DocumentElement.type` or `ComDocumentElement.com_type` model field types (they are already correct)
- Fixing other `# type: ignore` annotations in the project (separate changes)
- Adding new mypy strictness to `pyproject.toml` (separate concern)
- Changing test behavior or coverage

## Decisions

| # | Decision | Rationale | Alternatives Considered |
|---|----------|-----------|------------------------|
| 1 | **Narrow helpers to ElementType/ComElementType** | The Literal types already enforce the exact values the helpers pass. Narrowing is correct typing — the helpers should advertise the contract they fulfill. | Widening `DocumentElement.type` to `str` would lose type safety across the entire codebase (rejected). |
| 2 | **Import ElementType from extraction.model, ComElementType from enrichment.model** | These are the canonical sources already used by the model definitions. Existing imports already reference both modules, so no new import chains are created. | Redefining the Literal in the test file (code duplication, maintenance burden). |
| 3 | **Keep `# type: ignore[misc]` in test_patterns.py** | That suppression tests NamedTuple immutability — a legitimate test pattern where `entry.name = "other"` is *expected* to fail type-checking because the test asserts `AttributeError`. Removing it would require mypy to accept invalid assignment. | Removing it and using `cast` or `Any` (less direct, obscures the test intent). |
| 4 | **Both files follow identical pattern** | The helper functions in `test_assembler.py` and `test_boundaries.py` share the same structure (`_make_el`, `_make_com_el`). Applying the same fix to both ensures consistency. | Fixing only one file (leaves inconsistency). |

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| New mypy errors surface in the test files | Low | Low | Run `mypy tests/pdf_semantic_chunking/test_chunking/test_assembler.py tests/pdf_semantic_chunking/test_detection/test_boundaries.py` before and after to verify zero regressions |
| Another `# type: ignore[arg-type]` is needed for valid cases we missed | Very low | Low | The 5 direct-literal ignores being removed mirror 134 successful literal calls elsewhere — pattern is proven safe |
| ElementType/ComElementType import conflicts with existing names | Very low | Low | Neither `ElementType` nor `ComElementType` is imported in either file currently — no shadowing risk |
