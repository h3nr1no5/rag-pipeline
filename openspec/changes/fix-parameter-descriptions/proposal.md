## Why

Parameter descriptions from DOCX-based API documentation tables are silently lost during extraction. Every `APIParameter` created by the DOCX pipeline has `description=""`, because the table-row merging step destroys the continuation-row structure that the only description-capturing code path depends on. This degrades retrieval quality — parameter chunks show `CrossSectionName: BSTR` with no context about what the parameter means. A related bug in `_vb` alias handling creates fake parameter nodes with meaningless type annotations, polluting the chunk graph and search index.

## What Changes

### Fix 1: Parse merged continuation data for parameter descriptions

`merge_multi_row_functions()` (called at `manager.py:218`) collapses continuation rows into `\n`-separated cell text before the converter sees them. `_convert_method_table()` relies on separate rows with empty col0 to fill parameter descriptions — a code path that never fires after merging.

**Fix**: After creating a function in Path A, parse the already-merged `\n`-separated cells. Split col1/col2 on `\n`, skip the signature line, then iterate the remaining lines positionally: lines matching known parameter names fill `param.description`; non-matching lines append to `func.description`.

### Fix 2: Prevent merged continuation text from spilling into function names

When a function signature has no parentheses (no inline params), `name = col1.strip()` captures ALL merged continuation text (e.g., `DisableMainForm\nDisable all controls...`).

**Fix**: Split `col1` on `\n` first and only use the first line as the function name.

### Fix 3: Handle `_vb` alias functions correctly

Functions ending in `_vb` (e.g., `MessageDlg_vb`) use a parenthetical description format: `MessageDlg_vb (Visual Basic compatible function of MessageDlg)`. `_parse_inline_params` misinterprets this as a parameter with `name="MessageDlg"` and `type_annotation="Visual Basic compatible function of"`, creating a fake chunk graph node.

**Fix**: Detect the alias pattern by checking if `name.endswith("_vb")`, the function has exactly one parameter, and its `type_annotation` contains `"Visual Basic compatible function of"`. Clear the fake params and set `description` to `"VB-compatible alias for {original}"`.

## Capabilities

### New Capabilities

*(None — this is a bug fix that restores existing intended behavior.)*

### Modified Capabilities

- `com-structure-enrichment`: The existing spec requires parameter descriptions to be captured (line 31 of `com-structure-enrichment/spec.md` says "SHALL associate each description with its parameter by name"). This fix brings the DOCX extraction path into compliance with that requirement.

## Impact

| Area | Impact |
|------|--------|
| `extraction/converter.py` | `_convert_method_table()` gets ~20 lines of new logic after line 825 (merged continuation parsing, alias detection). All changes are in Path A. |
| `extraction/table_detector.py` | No change |
| `extraction/manager.py` | No change (pipeline order stays as-is) |
| Models (`model/models.py`) | No change (APIParameter.description already exists) |
| Chunk builder / text formatter | No change (they faithfully forward descriptions — they just receive empty ones currently) |
| Chunk graph | Fewer spurious parameter nodes for `_vb` aliases |
| Retrieval | Parameter chunks now include descriptions, improving BM25/embedding signal |
