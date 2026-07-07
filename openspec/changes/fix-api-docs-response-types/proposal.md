## Why

The API docs RAG response contains `relevant_functions` and `relevant_types` fields in `ApiDocQueryResponse`, but both are always empty (or near-empty) regardless of the query. This means the frontend's "Relevant Functions" and "Relevant Types" expandable sections never show useful information, and API consumers get no structured metadata about which identifiers the answer relates to. The root cause is an omission in `_query_fallback` (the path used for both DSPy-disabled and as fallback when DSPy fails): `interface_name` is read from chunk metadata and passed to individual `ApiDocSource` objects, but is never collected into `seen_functions` or `seen_types`. Interface nodes — the most common chunk type — silently vanish from the top-level response fields.

## What Changes

- **Fix `_query_fallback`**: Add `interface_name` to `seen_types` so interface names appear in the `relevant_types` field.
- **Fix `_query_dspy` fallback**: When the DSPy predictor returns empty `relevant_functions` / `relevant_types`, fall back to extracting them from the resolved sources (mirroring the `_query_fallback` logic) rather than propagating empty arrays.
- **Add spec requirements**: Document the expected behavior of `relevant_functions` and `relevant_types` in the `api-docs-rag` spec, including what metadata populates each field and fallback behavior.

## Capabilities

### New Capabilities
*(none — this change fixes existing behavior, not introduces new capabilities)*

### Modified Capabilities
- `api-docs-rag`: Add spec-level requirements for `relevant_functions` and `relevant_types` response fields. Define which metadata keys populate each field (`function_name`/`name` → functions, `type_name`/`interface_name` → types), and define fallback extraction behavior when the DSPy predictor omits these fields.

## Impact

- **Files modified**: `src/domain/rag/api_docs/manager.py` (both `_query_fallback` and `_query_dspy`)
- **Schema**: No changes to `ApiDocQueryResponse` or any Pydantic models — only the values assigned to existing fields
- **API**: No new endpoints or changed signatures. Response shape unchanged, but `relevant_functions` and `relevant_types` will now be populated
- **Frontend**: No frontend changes needed — it already renders these fields when non-empty (per `api-docs-frontend` spec Requirement: Response display SHALL show API doc-specific fields)
- **Tests**: Add/update tests verifying that `interface_name` is included in `relevant_types` and that DSPy fallback extraction works
