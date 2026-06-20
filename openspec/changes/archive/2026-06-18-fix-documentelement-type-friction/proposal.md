## Why

Two test files (`test_assembler.py`, `test_boundaries.py`) carry 9 stale `# type: ignore[arg-type]` annotations because their helper factory functions accept `str` instead of the proper `ElementType`/`ComElementType` literal types. Other test files (`test_model.py`, `test_fallback.py`, `test_classifier.py`) pass the same literal values directly without any ignore — proving these 9 suppressions are code archaeology left over from before the Literal types were refined. Cleaning them up reduces mypy debt by 50% (9 of 18 total ignores) and brings the test code in line with actual type safety.

## What Changes

- **Narrow helper parameter types** — 4 factory functions (`_make_el` ×2, `_make_com_el` ×2) change their type annotation from `str` / `str | None` to `ElementType` / `ComElementType | None`.
- **Remove stale `# type: ignore[arg-type]`** — 5 annotations on direct literal calls (e.g., `DocumentElement(type="PAGE", ...)`) are removed since mypy accepts the literal string as a valid `ElementType`.
- **One legitimate `# type: ignore[misc]`** in `test_patterns.py` (immutability test) is left untouched.

No runtime behavior changes. No new dependencies. No spec-level requirement changes.

## Capabilities

### New Capabilities

*(None — this is a code hygiene change with no new capability.)*

### Modified Capabilities

*(None — no spec-level requirements change.)*

## Impact

| File | Lines | Change |
|------|-------|--------|
| `tests/pdf_semantic_chunking/test_chunking/test_assembler.py` | 18, 42, 58, 110 | 1 parameter type narrowed + 3 ignores removed |
| `tests/pdf_semantic_chunking/test_detection/test_boundaries.py` | 23, 43, 52, 160, 528 | 1 parameter type narrowed + 4 ignores removed |
| `tests/pdf_semantic_chunking/test_.../test_patterns.py` | — | No change |

- **No runtime impact** — `ElementType` and `ComElementType` are `Literal` types, not runtime enums. The existing string values (`"PAGE"`, `"PARAGRAPH"`, etc.) are already valid members.
- **No dependency changes** — The types are already imported in both files (`DocumentElement`, `ComDocumentElement`). The Literal aliases (`ElementType`, `ComElementType`) need to be imported.
- **No test coverage changes** — All existing tests pass unmodified.
