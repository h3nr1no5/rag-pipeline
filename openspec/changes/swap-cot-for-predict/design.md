## Context

The `APIDocRAG` module (`src/domain/rag/api_docs/pipeline/module.py`) currently uses a two-tier generation strategy:

1. **Primary**: `dspy.ChainOfThought(APIResponseGenerator)` — produces 6 output fields (reasoning + answer + citations + relevant_functions + relevant_types + confidence) using DSPy's `[[ ## field_name ## ]]` structured format
2. **Fallback**: `dspy.Predict(APIResponseGenerator)` — produces 5 output fields (no reasoning) using the same structured format

The 1.5B Qwen model (MLX-optimized) frequently fails to produce the structured `[[ ## field_name ## ]]` format required by DSPy's `ChatAdapter`, especially when context is long (all retrieved chunks fed directly after `simplify-dspy-pipeline`). This causes `AdapterParseError` on the CoT path, triggering the Predict fallback. Predict can also fail for the same reason, producing error messages for end users.

The `reasoning` field from CoT is mapped to `ApiDocQueryResponse.reasoning_hint` but is never surfaced to users in the Streamlit UI. The `reasoning_hint` field always displays as empty string in practice.

## Goals / Non-Goals

**Goals:**
- Eliminate the primary source of `AdapterParseError` in the APIDocRAG pipeline
- Simplify the generation stage by removing the unused CoT/reasoning path
- Reduce code complexity (remove try/except, fallback, dual predictor setup)
- Maintain identical end-user experience (the reasoning field is not user-facing)

**Non-Goals:**
- Fixing the 1.5B model's structured output capability (would require a larger model)
- Changing the DSPy adapter layer itself (that's a separate, larger effort)
- Removing the `rationale` key from the API response schema (backward compatibility)
- Changing any behavior outside of the APIDocRAG module and its tests

## Decisions

### Decision 1: Use Predict as the sole generator

`dspy.Predict(APIResponseGenerator)` replaces `dspy.ChainOfThought(APIResponseGenerator)`.

**Rationale**:
- Predict has 5 output fields vs CoT's 6 — fewer fields means the 1.5B model is slightly more likely to format output correctly
- Predict does not inject a `reasoning` field into the signature, so the ChatAdapter has one less field header to require in the output
- The `reasoning`/`reasoning_hint` field provides no end-user value (never surfaced in Streamlit, always empty in practice)
- If Predict still fails (AdapterParseError), it fails at the same point — but the likelihood is lower with fewer fields

**Alternatives considered**:
- *Custom lenient adapter* (Option A from analysis): More robust but more complex to implement and test. Can be done as a follow-up if Predict still fails.
- *Keep CoT, lower temperature*: Would reduce format errors but also reduce answer quality (the original problem that prompted temperature 0.1→0.3).
- *Larger model*: Would fix the root cause but requires 2-4× download and slower inference.

### Decision 2: Remove the fallback generator entirely

The current `fallback_generator` is `dspy.Predict(APIResponseGenerator)` — the same as the new primary. With Predict as the sole generator, there is nothing to fall back to.

**Rationale**:
- A try/except around a Predict call that would do the exact same thing on retry provides no value
- If the sole Predict call fails, the error is caught at the `forward()` level and logged
- Simpler code, fewer paths to test

### Decision 3: Always return empty rationale

Since Predict has no `reasoning` field, the `rationale` key in the result dict will always be `""`.

**Rationale**:
- The `ApiDocQueryResponse.reasoning_hint` field already handles empty string (explicit fallback in `manager.py` line 477: `reasoning_hint=""`)
- The `_query_fallback()` path in manager.py already sets `reasoning_hint=""` — this is an established pattern
- No API consumers depend on non-empty rationale (Streamlit UI shows nothing)

## Risks / Trade-offs

- **[Regression] Existing tests verify fallback behavior** → All fallback-related tests will be removed or updated. The test file will need a thorough rewrite.
- **[Regression] rationale expected to be non-empty in some tests** → Tests that assert `len(rationale) > 0` must be updated to expect `""`.
- **[Performance] No material change** — Predict is slightly faster than CoT (no reasoning tokens) but this is negligible.
- **[Future] If CoT is needed later** — Re-introducing it is straightforward (swap back to `ChainOfThought` and add the field back).
