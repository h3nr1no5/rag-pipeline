## 1. Method chunk formatting — include parameter descriptions inline

- [ ] 1.1 In `_format_method()` (text_formatter.py:203): after the signature + function description, iterate `method.parameters` and append `\n  {name} ({type_annotation}): {description}` for each param that has a non-empty description
- [ ] 1.2 In `_meta_method()` (text_formatter.py:289): read `metadata["parameters"]` (list of `{name, type_annotation, description}` dicts) and apply the same inline formatting for params with descriptions
- [ ] 1.3 Verify that when `include_descriptions=False` no param detail lines are appended (existing behavior preserved)
- [ ] 1.4 Verify that when all param descriptions are empty, no extra lines are appended (no spurious output)

## 2. Metadata storage for method fallback

- [ ] 2.1 In the chunk graph builder (builder.py): when creating a method node, store `metadata["parameters"]` as a list of `{name, type_annotation, description}` dicts (currently only `param_count` is stored)
- [ ] 2.2 Verify the metadata round-trips through `ApiDocIndex` persistence (DB → load → `_meta_method` formatting)

## 3. Sharpen the DSPy prompt

- [ ] 3.1 In `APIResponseGenerator` (signatures.py): update the `answer` field description to include "parameter names, types, descriptions, and how to use the API. Include step-by-step instructions when applicable."
- [ ] 3.2 Add a grounding constraint: "Only use information from the context — do not invent API details."

## 4. Update existing tests

- [ ] 4.1 Locate existing tests for `ChunkTextFormatter` — add test case verifying `_format_method` output includes parameter description lines
- [ ] 4.2 Add test case verifying `_meta_method` includes parameter description lines from metadata
- [ ] 4.3 Add test case verifying `include_descriptions=False` suppresses parameter detail lines
- [ ] 4.4 Run: `uv run pytest tests/unit/test_api_docs_*.py -v` — confirm no regressions

## 5. Verify with real query

- [ ] 5.1 Run a query against `test_docx_81p.docx` asking "how to add cross section from catalog?" and verify the answer includes parameter names, types, and descriptions
- [ ] 5.2 Run a non-parameter query (e.g., "list available enums") and verify the answer remains concise and does not fabricate parameter details
