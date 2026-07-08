## Why

The DSPy pipeline and its fallback path still produce answers with hallucinated or omitted parameter details, despite recent fixes to parameter extraction (54eb9a7) and DSPy prompt enhancement (516a265, 12c8af0). Three root causes remain: (1) assertions detect hallucinated citations but take no corrective action, (2) the fallback prompt never directs the LLM to include parameter information, and (3) BM25 keyword search can't match parameter descriptions — only embedding search can — creating a retrieval blind spot.

## What Changes

### Change 1: Make assertions actionable — reject hallucinated output

When `_generate_with_assertions()` produces an answer with `assertions_passed: false` (meaning citations reference unknown functions/types or omit required elements), the system currently returns the output verbatim. After this change, failing assertions will trigger a retry with a strengthened instruction, and if all retries fail, a plain-text fallback answer reporting the available context.

### Change 2: Update fallback prompt to request parameter-level detail

`_generate_answer()` assembles a prompt that says "Use EXACT values from context. Do not invent names." but does not request parameter names, types, or descriptions. After this change, the fallback prompt will instruct the LLM to reproduce parameter names, types, and descriptions from the context.

### Change 3: Index per-parameter descriptions in BM25 keyword text

`ApiBm25Index._build_keyword_text()` for method nodes currently includes `interface_name`, `function_name`, `return_type`, and `description` — but not per-parameter names and descriptions. After this change, method-level keyword text will include flattened parameter names and descriptions so BM25 can match semantic queries about parameter usage.

### Change 4: Add answer-level validation that parameter details match context

When the DSPy pipeline generates an answer, validate that any parameter names and descriptions it includes actually appear in the retrieved source chunks. Unsupported claims will be flagged and optionally removed, extending the existing `response-verification` capability with citation-level parameter fact-checking.

## Capabilities

### New Capabilities

- `hallucination-detection`: Assertion results SHALL trigger corrective action (retry or fallback) rather than being advisory-only.

### Modified Capabilities

- `api-docs-rag`: The fallback query generation prompt SHALL request parameter names, types, and descriptions from the retrieved context.
- `retrieval`: The API-docs BM25 index SHALL include per-parameter names and descriptions in method-level keyword text for improved semantic keyword matching.
- `response-verification`: The verification system SHALL validate that parameter names and descriptions in the generated answer exist in the source chunks, with configurable removal of unsupported claims.

## Impact

| Area | Impact |
|------|--------|
| `pipeline/module.py` | `_generate_with_assertions()` — add retry logic on assertion failure; `MAX_CONTEXT_CHUNKS` may be revisited |
| `pipeline/assertions.py` | No change to assertion logic itself; module.py consumer changes |
| `pipeline/signatures.py` | No change (DSPy prompt already enhanced in 516a265) |
| `manager.py` | `_generate_answer()` fallback prompt updated to request parameter details |
| `retrieval/bm25_index.py` | `_build_keyword_text()` method branch — flatten `parameters` metadata into keyword text |
| `response-verification` spec | New requirement for parameter-level citation validation |
| `hallucination-detection` spec | New spec defining retry thresholds, fallback behavior |
