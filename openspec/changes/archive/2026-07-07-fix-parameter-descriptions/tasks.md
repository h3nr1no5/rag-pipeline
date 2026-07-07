## 1. Fix merged function name spillover (line 817)

- [x] 1.1 Ensure `col1.split("\n")[0]` is used when `col1` contains continuation text, preventing merged lines from spilling into the function name

## 2. Add merged continuation parsing for descriptions

- [x] 2.1 After `current_func` creation in Path A, add a helper to parse `\n`-separated merged cells: split col1/col2 on `\n`, skip the signature line from col1 and the function description from col2[0], iterate remaining lines positionally
- [x] 2.2 For each continuation line: check if it matches a known param name — if yes and col2 text exists, set `param.description`; otherwise append to `func.description`
- [x] 2.3 Verify the fix handles the case where a param name appears in continuation col1 but no corresponding text exists in continuation col2 (treat as function description text, matching existing Path B behavior at line 850-855)

## 3. Handle `_vb` alias functions

- [x] 3.1 After function creation, detect `_vb` alias pattern: `name.endswith("_vb")` AND exactly 1 param whose `type_annotation` contains `"Visual Basic compatible function of"`
- [x] 3.2 Clear fake params and set `description` to `"VB-compatible alias for {original}"`

## 4. Update existing tests

- [x] 4.1 Locate existing tests for DOCX extraction in `tests/unit/test_api_docs_extraction.py` — add test cases for merged continuation parsing verifying param descriptions are populated
- [x] 4.2 Add test case verifying function name does not include merged continuation text
- [x] 4.3 Add test case verifying `_vb` alias functions have no fake parameters and correct description
- [x] 4.4 Run existing test suite: `uv run pytest tests/unit/test_api_docs_*.py -v` — confirm no regressions

## 5. Verify with real DOCX

- [x] 5.1 Run pipeline on `tests/docs/test_docx_81p.docx` and verify parameter descriptions are populated (use the inspect script or a debug assertion)
- [x] 5.2 Run the E2E integration test: `uv run pytest tests/integration/test_api_docs_e2e.py -v` — confirm no regressions
