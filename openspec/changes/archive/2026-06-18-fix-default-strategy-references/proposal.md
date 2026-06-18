## Why

When the "default" chunking strategy was renamed to "recursive" in the editable-chunking-params change, two categories of stale reference to the old `"default"` strategy ID were missed: a frontend hardcoded fallback on the document upload page, and six query route fallback expressions. These cause the frontend to silently map to a non-existent strategy ID when the strategies API fails, and the backend to use an invalid strategy ID as a fallback in edge cases.

## What Changes

1. **Frontend**: Replace the hardcoded `{"Default": "default"}` fallback dropdown in `client/pages/4_📁_Documents.py` with `{"Recursive": "recursive"}` to map to a valid strategy ID when the API fails to return strategies.

2. **Backend query routes**: Update 6 fallback expressions in `src/api/routes/query/routes.py` from `else "default"` to `else "recursive"` so the fallback strategy ID is valid.

## Capabilities

### New Capabilities
*(none — this is a bug fix with no new capability)*

### Modified Capabilities
*(none — no spec-level requirement changes, purely implementation fixes)*

## Impact

- **Files modified**: `client/pages/4_📁_Documents.py`, `src/api/routes/query/routes.py`
- **No API changes**: No new endpoints, no schema changes
- **No DB changes**: No migration, no new models
- **No dependency changes**
- **No tests need updating**: The stale references are in fallback paths not exercised by existing tests
