## Why

The DSPy pipeline's multi-step orchestration (QueryAnalyzer → ContextAssembler → ChainOfThought) causes Qwen 1.5B to hallucinate answers. The fallback path (single Predict call with raw question + all chunks) produces correct answers reliably but lacks ChainOfThought reasoning display in the UI.

The root cause: a 1.5B model lacks the capacity for reliable multi-step reasoning. Each extra LLM call (QueryAnalyzer rewriting queries, ContextAssembler selecting chunks) introduces error that compounds into the final answer.

## What Changes

- **Remove QueryAnalyzer step**: Use the raw user question directly for hybrid retrieval instead of having the LLM rewrite it into search queries. The 1.5B model frequently generates bad search queries that miss relevant chunks.
- **Remove ContextAssembler step**: Feed all retrieved chunks directly to the response generator instead of having the LLM select/reorder them. The 1.5B model regularly drops relevant chunks from the assembled context.
- **Keep ChainOfThought for generation**: The `APIResponseGenerator` remains a `ChainOfThought` predictor so the reasoning trace is still captured and displayed in the frontend.
- **Keep assertions**: Citation/reference validation remains as advisory-only quality signals.

## Capabilities

### Modified Capabilities

- `api-docs-rag`: The `APIDocRAG.forward()` pipeline will skip query analysis and context assembly, using raw input + all retrieved chunks directly with the ChainOfThought generator.

## Impact

- **File**: `src/domain/rag/api_docs/pipeline/module.py` — `_forward_impl()` method simplified
- **No API changes**: The `ApiDocQueryResponse` schema is unchanged. `reasoning_hint` still populated from ChainOfThought.
- **No config changes**: `API_DOCS_DSPY_ENABLED` setting remains as-is. This fix applies within the DSPy path.
- **Tests**: Unit and integration tests in `tests/unit/rag/api_docs/` and `tests/integration/` may need updates since QueryAnalyzer/ContextAssembler are no longer invoked.
