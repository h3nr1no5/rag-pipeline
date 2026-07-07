## 1. Fix `_query_fallback` — interface name in relevant_types

- [x] 1.1 Add `interface_name` to `seen_types` set in `_query_fallback()` after the existing `type_name` check (line 483 of `manager.py`): if `interface_name` is non-empty and not already in `seen_types`, add it

## 2. Fix `_query_dspy` — post-hoc fallback extraction from sources

- [x] 2.1 In `_query_dspy()`, after mapping DSPy predictor output to `result["relevant_functions"]` and `result["relevant_types"]`, add fallback: if either list is empty, extract values from resolved sources by scanning their metadata
- [x] 2.2 Ensure fallback extraction uses the same metadata keys as `_query_fallback`: `function_name`/`name` → `relevant_functions`, `type_name`/`interface_name` → `relevant_types`
- [x] 2.3 Ensure fallback deduplicates via sets and sorts alphabetically (matching `_query_fallback` behavior)
- [x] 2.4 Verify the DSPy result dict merging works: non-empty DSPy output is preserved, only empty fields are filled by fallback

## 3. Unit tests

- [x] 3.1 Add unit test verifying `_query_fallback` includes `interface_name` in `relevant_types`
- [x] 3.2 Add unit test verifying `_query_fallback` does NOT include `interface_name` in `relevant_functions`
- [x] 3.3 Add unit test verifying `_query_dspy` fallback extracts from sources when DSPy returns empty `relevant_functions`
- [x] 3.4 Add unit test verifying `_query_dspy` preserves non-empty DSPy output without fallback
- [x] 3.5 Add unit test verifying `_query_dspy` partial fallback (one field from DSPy, other extracted)
- [x] 3.6 Add unit test verifying both paths return sorted, deduplicated lists
- [x] 3.7 Add unit test verifying empty metadata produces empty `[]` lists

## 4. Integration tests

- [x] 4.1 Verify `POST /api/v1/query/api-docs` response includes populated `relevant_functions` with function names
- [x] 4.2 Verify `POST /api/v1/query/api-docs` response includes populated `relevant_types` with interface names (not just `type_name`)

## 5. Verification

- [x] 5.1 Run unit tests (`uv run pytest tests/unit/ -v`)
- [x] 5.2 Run API docs integration tests (`uv run pytest tests/integration/ -k "api_docs" -v`)
- [x] 5.3 Run all fast tests (`uv run pytest -v -m "not slow"`)
- [x] 5.4 Run ruff and mypy (`uv run ruff check . && uv run mypy src/`)
- [x] 5.5 Manual smoke test: start backend, query an API doc with DSPy disabled, verify `relevant_types` includes interface names in response
- [ ] 5.6 Manual smoke test: start backend, query an API doc with DSPy enabled, verify `relevant_functions` and `relevant_types` are populated
