## Why

The `ChainOfThought(APIResponseGenerator)` predictor in `APIDocRAG` relies on DSPy's `[[ ## field_name ## ]]` structured output format, which the 1.5B Qwen model cannot reliably produce. This causes `AdapterParseError` at runtime, forcing an unnecessary fallback to `Predict`. Since the 1.5B model lacks the capacity to consistently format 6 output fields (reasoning + 5 content fields) alongside long retrieval contexts, CoT provides no practical benefit — the `reasoning` field is never surfaced to users and is only used as a `reasoning_hint` in the API response (always visible as empty string in the Streamlit UI). Removing CoT eliminates the primary source of pipeline parse errors without reducing end-user value.

## What Changes

- Replace `dspy.ChainOfThought(APIResponseGenerator)` with `dspy.Predict(APIResponseGenerator)` as the sole response generator in `APIDocRAG`
- Remove the `fallback_generator` (also `Predict`) and the `_generate_fallback` method entirely
- Simplify `_generate_with_assertions`: no try/except around the generator call (Predict has fewer output fields and cannot raise `AdapterParseError` from the ChatAdapter)
- Always return `"rationale": ""` in the result dict (Predict has no `reasoning` field)
- Update all tests in `test_api_docs_dspy_integration.py` to reflect Predict-only behavior (no fallback path, empty rationale)
- Update the existing spec `api-docs-rag` requirement about rationale propagation to reflect that rationale is always empty

## Capabilities

### New Capabilities
_(none — this is a simplification of an existing capability)_

### Modified Capabilities
- `api-docs-rag`: The requirement "Pipeline SHALL propagate rationale from DSPy predictor" changes — rationale will always be an empty string since Predict has no `reasoning` field. The `ApiDocQueryResponse.reasoning_hint` field will always be empty. The fallback-path scenario is removed since there is no fallback.

## Impact

- **`src/domain/rag/api_docs/pipeline/module.py`**: Remove `self.response_generator` (CoT), rename `self.fallback_generator` → `self.response_generator` (Predict), simplify `_generate_with_assertions`, remove `_generate_fallback`
- **`tests/unit/domain/rag/api_docs/test_api_docs_dspy_integration.py`**: Remove fallback-path tests, update rationale tests to expect empty string, remove CoT-specific mocks
- **`openspec/specs/api-docs-rag/spec.md`**: Update the "Pipeline SHALL propagate rationale" requirement
- **`src/domain/rag/api_docs/manager.py`** (if it references `reasoning` from Predict): No change expected — already handles empty rationale
- No new dependencies, no env var changes, no config changes
