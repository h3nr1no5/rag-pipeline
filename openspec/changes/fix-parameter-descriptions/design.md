## Context

The api-docs DOCX extraction pipeline has three stages: (1) parse DOCX into raw tables/paragraphs, (2) detect table types and merge multi-row functions, (3) convert raw tables into domain objects. Stage 2 (`merge_multi_row_functions`) runs before stage 3 (`DocumentConverter.convert`), which means by the time `_convert_method_table` processes a method table, all continuation rows have been collapsed into `\n`-separated cell text.

The only code path that fills parameter descriptions (`converter.py:834-839`) requires separate rows with empty column 0. Since those rows no longer exist after merging, all `APIParameter.description` values remain `""`.

Two secondary bugs share the same root cause:
- Function names without inline parentheses capture `\n`-concatenated continuation text
- `_vb` alias parentheticals are parsed as fake parameters

All three fixes are scoped to a single method: `_convert_method_table` in `converter.py`, specifically the "Path A" branch (non-empty column 0 → new function).

## Goals / Non-Goals

**Goals:**
- Parameter descriptions are populated from DOCX table continuation rows
- Function descriptions are populated from DOCX table continuation text
- Function names don't include merged continuation lines
- `_vb` alias functions don't produce fake parameter nodes
- Zero changes to model files, pipeline orchestration, or table type detection

**Non-Goals:**
- No changes to the PDF pipeline (`com-structure-enrichment`)
- No changes to the table merging logic (`merge_multi_row_functions`)
- No new models or database migrations
- No changes to chunk graph building or text formatting (they already forward descriptions faithfully)
- No changes to how parameters are stored in the chunk graph

## Decisions

### Decision 1: Parse merged cells inline rather than changing pipeline order

**Chosen**: After creating the `APIFunction` in Path A, parse the `\n`-separated cell content to extract descriptions from continuation lines.

**Alternatives considered:**
- **Reorder pipeline (merge after convert)**: Would require changing `manager.py` and potentially breaking other table types that depend on merging. Higher blast radius.
- **Skip merging for method tables**: Would require passing table type info into `merge_multi_row_functions`, coupling merging logic to detection logic. Higher complexity.
- **Unmerge cells before Path B**: More complex — would need to reconstruct virtual continuation rows. The existing Path B logic assumes physical rows.

**Rationale**: The inline parsing approach is the most targeted fix. It works with the existing merged data, requires no pipeline changes, and all logic stays in one method.

### Decision 2: Use positional matching for merged continuation rows

The merged cells preserve row order: `col1[i]` corresponds to `col2[i]` from the same original table row. After splitting on `\n`, lines at the same index in col1 and col2 were from the same continuation row.

Col1 continuation lines are checked against known parameter names. If they match, the corresponding col2 line becomes the parameter description. If they don't match (or if a known param name has no col2 text), the text is treated as function description material — replicating the existing Path B logic.

### Decision 3: Detect `_vb` aliases by pattern matching

The `_vb` alias pattern is: function name ends with `_vb`, exactly one parameter, and that parameter's `type_annotation` contains `"Visual Basic compatible function of"`. This is a structural pattern that can be detected reliably without string heuristics.

**Alternatives considered:**
- **Regex on the full cell text**: More fragile — the format could vary
- **External alias list**: Requires maintenance, doesn't scale
- **Strip `_vb` and deduplicate against known functions**: Would require cross-referencing in the converter, which operates table-by-table

**Rationale**: The structural pattern is reliable. The DOCX format consistently uses this exact parenthetical structure for VB alias functions. Clearing the fake params and setting a description prevents the chunk builder from creating spurious parameter nodes.

### Decision 4: Don't add `alias_for` field to `APIFunction`

A cleaner model would add `alias_for: str | None` to `APIFunction` and let downstream consumers (chunk builder, text formatter) decide how to render aliases. However, that requires changes in 3 additional files (model, builder, text formatter) vs. 1 file with a description-based approach.

The description approach produces a chunk like `"MessageDlg_vb() -> EMessageDialogButton* — VB-compatible alias for MessageDlg"` — informative for both search and display.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Multi-paragraph cells (cell text contains natural `\n`) could be mis-parsed as continuation rows | In practice, signature cells in DOCX tables rarely have multi-paragraph content. Any extra lines would be matched against param names and either set descriptions (low risk) or become part of the function description (harmless). |
| Parameter names with trailing whitespace or special characters could fail to match | Both col1 continuation text and known param names are stripped before comparison. No known failures. |
| A non-`_vb` function with exactly one param whose type annotation mentions "Visual Basic" could be misclassified | The pattern requires BOTH `name.endswith("_vb")` AND the specific type annotation text. False positives are effectively impossible given the DOCX source format. |
| Functions without inline params (params listed only in continuation rows) still won't get param descriptions | This is a pre-existing limitation of the DOCX format. When params aren't in the signature, there's no way to match continuation lines to param objects. Acceptable — the majority of functions use inline params. |
