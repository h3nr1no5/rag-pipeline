## Context

The `APIDocRAG` DSPy module uses three `dspy.ChainOfThought` predictors: QueryAnalyzer, ContextAssembler, and APIResponseGenerator. Each produces an internal `rationale` field containing the model's step-by-step reasoning. The existing code in `module.py` only reads the output fields (`.answer`, `.citations`, etc.) and discards `.rationale` entirely. The response schema `ApiDocQueryResponse` has no field for reasoning, and the frontend `Chat.py` has no display component for it.

The `fix-api-docs-answer-quality` change (previous change) deliberately chose to embed CoT reasoning inline in the `answer` field by modifying the DSPy signature description. This is complementary — the `answer` contains the final synthesis with reasoning baked in, while the new `reasoning_hint` exposes the raw, unedited ChainOfThought rationale as an observability signal.

## Goals / Non-Goals

**Goals:**
- Capture `response.rationale` from `APIResponseGenerator` (the only predictor whose rationale is user-relevant)
- Add `reasoning_hint: str` to `ApiDocQueryResponse` schema
- Pipe the rationale through `APIDocRAG._generate_with_assertions()` → `_forward_impl()` → `manager._build_dspy_response()` → `ApiDocQueryResponse`
- Display `reasoning_hint` as an expandable "💭 Reasoning" section below the answer in the chat UI
- Leave `reasoning_hint` empty (`""`) for the fallback path (non-DSPy `_generate_answer()`)

**Non-Goals:**
- NOT capturing QueryAnalyzer or ContextAssembler rationales (internal to pipeline stages, not user-visible)
- NOT populating `reasoning_content` in `MLXDspyLM._build_chat_completion()` — that field is a DSPy-internal OpenAI compatibility stub, not consumed by the pipeline
- NOT adding streaming support for the reasoning hint
- NOT modifying the fallback `_generate_answer()` prompt or behavior
- NOT caching the reasoning hint separately (it piggybacks on the existing response flow)

## Decisions

### Decision 1: Capture rationale from APIResponseGenerator only

**Chosen**: Only capture `response.rationale` from the `APIResponseGenerator` predictor.

- **Why**: This is the final generation stage — the rationale explains how the model arrived at the answer. QueryAnalyzer and ContextAssembler rationales are internal to the pipeline (query decomposition and chunk selection) and would confuse users.
- **Alternatives considered**: Capturing all three rationales. **Not chosen** — too noisy, and the intermediate rationales are not useful for the "hint" purpose.

### Decision 2: Raw CoT rationale, no post-processing

**Chosen**: Store the raw DSPy rationale text as-is in `reasoning_hint`.

- **Why**: The raw text is the most authentic representation of the model's reasoning. Post-processing (trimming, reformatting, or summarizing) risks losing information or introducing artifacts.
- **Why not truncated/trimmed**: The user explicitly said length is not a concern. The expandable component naturally hides the verbosity until the user opts in.

### Decision 3: Expandable component (same pattern as Sources/Functions/Types)

**Chosen**: Use Streamlit's `st.expander("💭 Reasoning")` placed between the confidence badge and the Functions section.

- **Why**: Follows the existing UI pattern (Sources, Functions, Types all use expandable sections). Consistent user experience.
- **Alternatives considered**: Tooltip on hover (rejected by user in favor of expandable). Inline text (too prominent for a "hint"). Separate tab (too much navigation overhead).

### Decision 4: Leave `reasoning_content=None` in `MLXDspyLM`

**Chosen**: No changes to `lm_adapter.py`.

- **Why**: `reasoning_content` is an OpenAI o-series API field. DSPy's `BaseLM._process_completion()` does not read it — it only reads `.message.content`. Setting it would have zero functional impact and create a misleading signal (DSPy's `reasoning_content` is not the same as the CoT rationale chain).
- **The actual rationale extraction happens through DSPy's `ChainOfThought` parsing**, which produces `response.rationale` on the Prediction object. This is a separate mechanism from `reasoning_content`.

## Risks / Trade-offs

- **[Risk] Raw rationale text may be verbose or contain incomplete sentences** — The model's CoT output is unpolished by nature. Mitigation: The expandable component is collapsed by default, so users opt in to see it. Hints are informational, not critical.
- **[Risk] Fallback path has no rationale** — When the non-DSPy path is used, `reasoning_hint` is empty. Mitigation: The expander simply isn't rendered when the string is empty. No broken UI.
- **[Risk] Rationale could leak internal prompts or chunk IDs** — DSPy's CoT sometimes references internal representations. Mitigation: This is inherently limited — the model references chunk IDs that are already visible in the Sources expander. No sensitive information is exposed.
