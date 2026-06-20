## Context

The "editable-chunking-params" change renamed the strategy ID `"default"` to `"recursive"` across the codebase (seed data, startup migration, entity definitions, tests, frontend logic). However, two categories of stale fallback reference were missed because they live in code paths that only activate in edge cases:

1. **Frontend**: When `GET /strategies` returns an empty list (API unavailable), the upload page fell back to `{"Default": "default"}` — both the label and the strategy ID reference the non-existent strategy.
2. **Backend query routes**: Six route handlers use `else "default"` as a fallback when `doc_strategies` is empty. Since query routes require at least one document ID to be called, this fallback is only reachable if a document has no associated strategy — an edge case that should no longer occur after the migration, but the fallback value itself is invalid.

## Goals / Non-Goals

**Goals:**
- Eliminate all references to the non-existent `"default"` strategy ID
- Ensure all fallback paths reference a valid strategy ID (`"recursive"`)
- Minimal, safe changes with no behavioral risk

**Non-Goals:**
- No architectural changes
- No new tests (fallback paths are not exercised by existing tests and are defensive code)
- No spec-level changes (this is a pure implementation fix)

## Decisions

1. **One-line string replacement for query routes** — Using `replaceAll` with a sufficiently unique pattern (`else "default"` → `else "recursive"`) across all 6 occurrences. The pattern is unique enough that `replaceAll` can safely apply without false matches.

2. **Frontend fallback dictionary change** — Replace `{"Default": "default"}` with `{"Recursive": "recursive"}`. This keeps the existing guard check pattern — if the API fails, the user still sees a dropdown with a valid strategy. Alternative considered: disabling the upload form entirely when strategies can't load, but that would be a behavior change with potential UX regressions.

3. **No test changes needed** — The frontend fallback path (`if not strategies`) and query route fallback (`else "default"`) are defensive edge cases not exercised by current tests. Changing the fallback value doesn't introduce new behavior to test.

## Risks / Trade-offs

- **Low risk**: Both changes are simple string replacements in fallback code paths. The frontend change only affects the case where the strategies API returns an empty list. The backend change only affects the case where a document has no strategies — which the startup migration should prevent.
- **No spec changes needed**: This is a pure implementation fix, no requirement-level changes.
