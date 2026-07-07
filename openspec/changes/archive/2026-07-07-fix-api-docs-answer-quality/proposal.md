## Why

The API documentation RAG endpoint (`/api/v1/query/api-docs`) frequently returns "I don't have enough information to answer this question" even when the retrieved sources contain the correct answer. This undermines user trust and makes the API doc feature unreliable. The problem is in the generation stage — a combination of overly conservative DSPy prompts, hard citation assertions that degrade quality on failure, low temperature (0.1), and response verification that strips technical API text.

## What Changes

1. **DSPy answer field rewritten** — Change `APIResponseGenerator.answer` to encourage detailed, step-by-step answers that include reasoning inline (the ChainOfThought-style analysis becomes the answer itself, not a separate field)

2. **DSPy assertions relaxed** — `validate_citations()` and `check_question_references()` become advisory: log warnings and report in response metadata but do NOT trigger fallback to `Predict`. Accept the ChainOfThought output regardless of citation formatting.

3. **Temperature raised to 0.3** — Increase `llm_temperature` from 0.1 to 0.3 for the api-docs pipeline to reduce conservative hedging.

4. **`verification_enabled` per-request toggle** — Add `verification_enabled` field to `ApiDocQueryRequest` schema and pipe it through the pipeline so frontend can toggle off verification for api-docs queries.

5. **ResponseVerifier behavior tuned** — When verification is enabled for api-docs DSPy path, use a higher bar for stripping sentences (require stronger evidence before declaring a sentence unsupported). Prefer to keep the answer intact.

## Capabilities

### New Capabilities

- `api-docs-answer-generation`: Configurable answer generation for API documentation queries including reasoning mode, temperature, and verification toggles

### Modified Capabilities

*(No existing specs to modify — this is the first spec creation)*

## Impact

- **src/domain/rag/api_docs/pipeline/signatures.py** — `APIResponseGenerator.answer` field description changed
- **src/domain/rag/api_docs/pipeline/module.py** — `_generate_with_assertions()` relaxed to log-only assertions, no fallback; capture full CoT reasoning in answer
- **src/domain/rag/api_docs/pipeline/assertions.py** — `validate_citations()` and `check_question_references()` become advisory
- **src/domain/rag/api_docs/pipeline/schemas.py** — `ApiDocQueryRequest` gains `verification_enabled` field
- **src/domain/rag/api_docs/manager.py** — `_query_dspy()` and `_build_dspy_response()` pipe `verification_enabled` through; temperature raised; verification behavior tuned
- **src/domain/rag/api_docs/routes.py** — pass `verification_enabled` to `_manager.query()`
- **client/utils/query.py** — `api_docs_query()` passes `verification_enabled` parameter
- **client/pages/3_💬_Chat.py** — frontend checkbox for api-docs verification toggle (optional)
- **src/core/config.py** — `llm_temperature` default raised to 0.3 (or add `api_docs_temperature` override)
