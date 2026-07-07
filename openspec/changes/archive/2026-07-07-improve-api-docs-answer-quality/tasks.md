## 1. Method chunk formatting — include parameter descriptions inline

- [x] 1.1 In `_format_method()` (text_formatter.py:203): after the signature + function description, iterate `method.parameters` and append `\n  {name}: {description}` for each param that has a non-empty description
- [x] 1.2 In `_meta_method()` (text_formatter.py:289): read `metadata["parameters"]` (list of `{name, description}` dicts) and apply the same inline formatting for params with descriptions
- [x] 1.3 Verify that when `include_descriptions=False` no param detail lines are appended (existing behavior preserved)
- [x] 1.4 Verify that when all param descriptions are empty, no extra lines are appended (no spurious output)

## 2. Metadata storage for method fallback

- [x] 2.1 In the chunk graph builder (builder.py): when creating a method node, store `metadata["parameters"]` as a list of `{name, description}` dicts (currently only `param_count` is stored)
- [x] 2.2 Verify the metadata round-trips through serialize/deserialize (parameters metadata survives round-trip)

## 3. Sharpen the DSPy prompt

- [x] 3.1 In `APIResponseGenerator` (signatures.py): update the `answer` field description to include "parameter names, types, and descriptions where relevant to the question"
- [x] 3.2 Add a grounding constraint: "Only use information that is present in the provided context — do not invent API details, parameter names, or behavior"

## 4. Update existing tests

- [x] 4.1 Locate existing tests for `ChunkTextFormatter` — add test case verifying `_format_method` output includes parameter description lines
- [x] 4.2 Add test case verifying `_meta_method` includes parameter description lines from metadata
- [x] 4.3 Add test case verifying `include_descriptions=False` suppresses parameter detail lines
- [x] 4.4 Run: `uv run pytest tests/unit/ -q` — 684 passed, no regressions ✓

## 5. Verify with real query (optional — skip for now)

- [ ] 5.1 Run a query against `test_docx_81p.docx` asking "how to add cross section from catalog?" and verify the answer includes parameter names, types, and descriptions
- [ ] 5.2 Run a non-parameter query (e.g., "list available enums") and verify the answer remains concise and does not fabricate parameter details
