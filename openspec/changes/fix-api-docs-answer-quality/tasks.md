## 1. DSPy Signature — CoT Answer Field

- [x] 1.1 Update `APIResponseGenerator.answer` field description in `signatures.py` to encourage detailed step-by-step reasoning (inline CoT as answer)

## 2. DSPy Assertions — Advisory Mode

- [x] 2.1 Modify `_generate_with_assertions()` in `module.py`: log citation/reference warnings but accept CoT output regardless of assertion results
- [x] 2.2 Remove the `_generate_fallback()` call from assertion failure paths — always return original CoT answer

## 3. LLM Temperature — Raise to 0.3

- [x] 3.1 Add `api_docs_temperature` to Settings in `src/core/config.py` (default `0.3`)
- [x] 3.2 Update `_query_dspy()` and `_query_fallback()` in `manager.py` to pass temperature through to the LLM call
- [x] 3.3 Update `MLXDspyLM` or the DSPy config to use `api_docs_temperature` when generating for the api-docs pipeline

## 4. Per-Request Verification Toggle

- [x] 4.1 Add `verification_enabled: bool = True` field to `ApiDocQueryRequest` in `schemas.py`
- [x] 4.2 Update `_manager.query()` signature to accept and forward `verification_enabled`
- [x] 4.3 Update route handler `query_api_docs()` in `routes.py` to pass `request.verification_enabled` to `_manager.query()`
- [x] 4.4 Update `_build_dspy_response()` in `manager.py` to skip `ResponseVerifier` when `verification_enabled=False`
- [x] 4.5 Update `_generate_answer()` in `manager.py` to skip `ResponseVerifier` when `verification_enabled=False`

## 5. Verification Threshold Tuning (DSPy Path)

- [x] 5.1 In `_build_dspy_response()` in `manager.py`, when verification is enabled on DSPy output, use a stricter threshold: only strip sentences scoring below `verification_similarity_threshold * 0.5`

## 6. Frontend — Verification Toggle

- [x] 6.1 Update `api_docs_query()` in `client/utils/query.py` to accept and pass `verification_enabled` parameter
- [x] 6.2 Add checkbox to `client/pages/3_💬_Chat.py` sidebar for api-docs verification toggle (disabled when api-docs not selected)

## 7. Tests

- [x] 7.1 Update DSPy module tests to verify advisory assertion behavior (no fallback on citation failure)
- [x] 7.2 Add test for `verification_enabled=False` request on api-docs endpoint
- [x] 7.3 Run full test suite and confirm no regressions
