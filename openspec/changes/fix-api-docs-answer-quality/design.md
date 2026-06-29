## Context

The `/api/v1/query/api-docs` endpoint uses a DSPy-powered pipeline with two paths:

1. **DSPy path** (tried first): `QueryAnalyzer (CoT) → HybridRetriever → ContextAssembler (CoT) → APIResponseGenerator (CoT) → assertions check → fallback Predict → ResponseVerifier`
2. **Fallback path**: `_generate_answer()` prompt + ResponseVerifier

Investigation found that retrieved sources consistently contain the correct answer, but the generation stage produces "I don't have enough information" due to:

- DSPy's `APIResponseGenerator.answer` field encourages short-form answers — model omits reasoning
- Hard citation assertions (`validate_citations`) degrade quality: when CoT output lacks perfect `[FunctionName]` formatting, system falls back to plain `Predict` (no reasoning), producing worse answers
- Temperature 0.1 makes the small 1.5B model overly conservative — it takes the "safe" path of refusing
- ResponseVerifier cross-encoder scores technical API text poorly, stripping valid sentences
- `ApiDocQueryRequest` lacks per-request `verification_enabled` toggle — frontend settings for verification are silently ignored by this endpoint

## Goals / Non-Goals

**Goals:**
- Make DSPy CoT output the answer directly (detailed reasoning included inline)
- Make citation assertions advisory — log problems but don't fall back to Predict
- Raise temperature from 0.1 to 0.3 for api-docs queries
- Add `verification_enabled` to `ApiDocQueryRequest` for per-request control
- Tune ResponseVerifier to be less aggressive on DSPy path output

**Non-Goals:**
- Not changing the generic `/api/v1/query` endpoint behavior
- Not changing the fallback `_generate_answer()` prompt (the DSPy path is the primary path; if DSPy is disabled, the fallback behavior is acceptable)
- Not adding streaming or new API endpoints
- Not changing the hybrid retrieval pipeline

## Decisions

### Decision 1: Full CoT output as answer (Option A)

**Chosen approach**: Change `APIResponseGenerator.answer` field description to encourage a detailed, step-by-step response that walks through analysis and includes reasoning inline.

- **Why**: The CoT reasoning IS the most useful answer for API documentation queries. It naturally walks through what the question asks, what functions/types are relevant, and how to use them. The current system's attempt to produce a short answer + separate citations loses the narrative thread.
- **Alternatives considered**:
  - **Option B** (capture raw CoT text from LM adapter): More invasive, requires modifying `MLXDspyLM` to stash raw output and piping it through the module. Parsing DSPy internals is fragile.
  - **Why not**: Option A is a single-line change to the signature description that naturally steers the model toward inline reasoning in the `answer` field. No architecture changes needed.

### Decision 2: Advisory assertions (log-only, no fallback)

**Chosen approach**: `_generate_with_assertions()` still validates citations and references, but logs warnings instead of falling back to `Predict`. The CoT output is accepted regardless of assertion results.

- **Why**: The fallback `Predict` (no chain-of-thought) produces markedly worse answers for a 1.5B model. Accepting a CoT answer with imperfect citations is strictly better than replacing it with a Predict answer. Citations are still reported in response metadata for observability.
- **Alternatives considered**: Removing assertions entirely. **Not chosen** because the metadata is useful for debugging and future optimization.

### Decision 3: Temperature raised to 0.3

**Chosen approach**: Set `llm_temperature = 0.3` for api-docs pipeline (configurable via Settings).

- **Why**: 0.1 produces near-deterministic output where the model defaults to the safest token path. 0.3 provides enough exploration for the model to construct longer, more confident answers while remaining mostly factual.
- **Why not higher (0.5-0.7)**: Risk of hallucination increases. For API documentation (factual, precise), consistency matters more than creativity.

### Decision 4: `verification_enabled` per-request field

**Chosen approach**: Add `verification_enabled: bool = True` to `ApiDocQueryRequest`. Route handler passes it to `_manager.query()`. When `False`, skip ResponseVerifier entirely. When `True` (default), behavior remains as-is.

- **Why**: Gives frontend users control. Some API doc queries are exploratory and don't need strict verification. The generic endpoint already has this pattern.

### Decision 5: Verification threshold tuning for DSPy path

**Chosen approach**: On the DSPy path, when verification is enabled, use a higher-evidence bar before stripping sentences. Specifically, only strip sentences where the cross-encoder score is below `verification_similarity_threshold * 0.5` (effectively requiring stronger evidence of unsupported claims).

- **Why**: Technical API prose (function signatures, parameter descriptions) scores lower on semantic similarity against a generic cross-encoder than conversational text. The current threshold (0.0, meaning strip if below 0) is too aggressive for this domain.
- **Risk**: May let through some unsupported claims. Mitigated by the fact that DSPy CoT already grounds its reasoning in the provided context.

## Risks / Trade-offs

- **[Risk] Factual accuracy may decrease slightly** — Relaxing assertions and tuning verification means fewer answers are rejected. Mitigation: assertions still log warnings for manual review; answer quality is observable via confidence field.
- **[Risk] Temperature 0.3 may introduce occasional hallucination** — The 1.5B model at higher temperature might generate plausible-looking but incorrect API details. Mitigation: the answer is still grounded in context via the prompt; verification (if enabled) still catches unsupported sentences.
- **[Trade-off] Longer answers** — CoT-style answers are more verbose. This increases token usage per query. Acceptable given the model runs locally (no API cost) and the improvement in answer quality.
- **[Trade-off] Per-request verification toggle adds API surface** — Adding fields to request schema increases maintenance burden. Acceptable because the generic endpoint already has this pattern, making it consistent.
