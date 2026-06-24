## Context

The DOCX parser detects heading levels by matching paragraph style names against known heading prefixes (`"Heading"`, `"Head"`, `"Title"`, `"Caption"`). For numbered heading styles like `"Heading 1"` or `"Heading 2"`, it strips the prefix and parses the remainder as a digit to get the level (1–6). However, Word also supports a bare `"Heading"` style (no number suffix) which is equivalent to `"Heading 1"` — it's the default top-level heading style.

The `get_heading_level()` function currently returns `0` for bare `"Heading"` because after stripping the prefix, the empty remainder fails `"".isdigit()`. This means paragraphs using the bare `"Heading"` style are not recognized as headings at all.

The Axis COM documentation uses bare `"Heading"` style for its top-level interface sections (e.g., `IAxisVMApplication`). Because these are not recognized as headings, all tables in those sections fall through to the `"Unknown"` interface in the converter output.

## Goals / Non-Goals

**Goals:**
- Bare `"Heading"` style paragraphs are recognized as headings at level `0` (above `Heading 1`)
- The heading nesting hierarchy works correctly: bare `"Heading"` > `"Heading 1"` > `"Heading 2"` > ...
- The non-heading sentinel value changes from `0` to `-1` to avoid ambiguity
- All existing numbered heading styles (`Heading 1–6`) continue working unchanged
- All existing tests pass with updated expectations

**Non-Goals:**
- No changes to heading level detection for `"Title"` or `"Subtitle"` styles (these work correctly)
- No changes to the converter logic beyond the heading stack filter
- No new spec files (the heading level detection behavior is not specified in existing specs)
- No changes to `"Caption"` style treatment

## Decisions

### Decision: Bare `"Heading"` → level `0` (not level `1`)
- **Why:** `"Heading 1"` already maps to level `1`. If bare `"Heading"` also maps to `1`, they'd be siblings — not nested. The user confirmed that `"Heading 1"` sections should be nested under `"Heading"` sections. Level `0` is a natural choice: it's above level `1`, distinct from `"Heading 1"`, and the heading stack logic handles it correctly (lower number = higher in hierarchy).
- **Alternatives considered:** 
  - Mapping bare `"Heading"` to `1` and `"Heading N"` to `N+1` — rejected because it shifts standard Word numbering and breaks existing tests.
  - Making bare `"Heading"` a special case in the converter — rejected because it spreads concern across two files.

### Decision: Non-heading sentinel changes from `0` to `-1`
- **Why:** With bare `"Heading"` now returning `0`, we need a different sentinel for "not a heading" to avoid ambiguity. `-1` is a clean negative sentinel that works with the `>= 0` filter in the converter.
- **Alternatives considered:** Using `None` for the default — rejected because it adds type complexity.

### Decision: Converter filter changes from `> 0` to `>= 0`
- **Why:** Bare `"Heading"` at level `0` needs to be included in the heading stack. Changing from strict `> 0` to `>= 0` allows this while still excluding `-1` (non-headings).
- **Risk:** None — this is a safe, targeted change.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Existing documents that use `"Heading"` style are now treated differently | This is the **intended fix** — they were previously broken (assigned to `"Unknown"`) |
| Non-heading `RawParagraph` objects with heading_level `0` could be misinterpreted as bare-`Heading` paragraphs | The sentinel change to `-1` eliminates this ambiguity — `0` is now exclusively used for bare `"Heading"` |
| The PDF fallback returns `-1` for heading_level, which could break code that checks `if heading_level > 0` | The converter filter is being updated to `>= 0`, so `-1` values are correctly excluded |
