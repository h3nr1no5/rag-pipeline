## 1. Response Schema

- [x] 1.1 Add `reasoning_hint: str = ""` field to `ApiDocQueryResponse` in `src/domain/rag/api_docs/pipeline/schemas.py`

## 2. Pipeline — Capture Rationale in Module

- [x] 2.1 In `src/domain/rag/api_docs/pipeline/module.py`, `_generate_with_assertions()`: capture `response.rationale.strip()` and include `"rationale"` key in the return dict
- [x] 2.2 In `_generate_fallback()`: include `"rationale": ""` in the return dict
- [x] 2.3 In `_forward_impl()`: pipe the `"rationale"` value through to the final return dict (it already passes `result` through, but verify `result["rationale"]` is included)

## 3. Manager — Pipe to Response

- [x] 3.1 In `src/domain/rag/api_docs/manager.py`, `_build_dspy_response()`: pass `result.get("rationale", "")` to `reasoning_hint` in the `ApiDocQueryResponse` constructor call
- [x] 3.2 In `_query_fallback()`: include `reasoning_hint=""` in the `ApiDocQueryResponse` constructor call

## 4. Frontend — Display Reasoning Hint

- [x] 4.1 In `client/pages/3_💬_Chat.py`: after the confidence badge block and before the Relevant Functions expander block, add `st.expander("💭 Reasoning")` that renders `reasoning_hint` when non-empty
- [x] 4.2 Store `reasoning_hint` from `api_docs_result` in the assistant message dict

## 5. Tests

- [x] 5.1 Add unit test in `tests/unit/domain/rag/api_docs/` verifying `_generate_with_assertions()` return dict includes `"rationale"` key
- [x] 5.2 Add integration test verifying `POST /api/v1/query/api-docs` response includes `reasoning_hint` field
- [x] 5.3 Verify fallback path returns `reasoning_hint: ""`
- [x] 5.4 Run existing test suite to confirm no regressions
