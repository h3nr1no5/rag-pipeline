## Context

The api-docs DSPy pipeline currently formats retrieved chunks with a `[uuid]` prefix (line 52 of `module.py`: `f"[{node.chunk_id}]\n{content}"`). The `APIResponseGenerator` signature instructs the LLM to "verify each claim with citation numbers in [brackets]". The LLM reproduces these UUIDs inline in the answer, producing output like:

```
The GetMaterial method takes three parameters [41205821-9d08-...].
```

The `clean_response()` post-processor strips `[Source N]` and `[Page N]` markers but lacks UUID-pattern stripping. The existing `📚 Sources` expander in the Streamlit UI already provides full source attribution — the inline UUIDs add noise without value.

## Goals / Non-Goals

**Goals:**

- Remove UUID/ID prefixes from chunk context passed to the DSPy LLM
- Remove inline citation instructions from the DSPy `APIResponseGenerator` signature
- Simplify `validate_citations` assertion to stop requiring inline `[Name]` markers
- Add UUID-stripping as defense-in-depth in `clean_response()`
- Update tests to match the new assertion behavior
- The `citations` output field (list of function/type names) remains — the DSPy `APIResponseGenerator` still produces this

**Non-Goals:**

- No changes to the chunking, indexing, or retrieval pipeline
- No changes to the Streamlit UI or API response schema (`sources` field stays unchanged)
- No changes to the `check_question_references` assertion (it works by plain-text matching, not bracket markers)
- No changes to the non-DSPy RAG paths (LangChain, LlamaIndex, cosine-similarity — they use `build_prompt` with `[Source N]` labels, which `clean_response` already handles)
- No changes to the metrics module — the `citation_accuracy` and `hallucination_rate` metrics use the separate `citations` output field (list of names) which remains populated by the DSPy pipeline

## Decisions

### Decision 1: Remove chunk UUID prefix in `_format_chunks()`

**Choice**: Pass only the chunk content, no prefix.

**Rationale**: The `[chunk_id]` prefix existed solely for inline citation. Since we're no longer asking the LLM to cite, the prefix is dead weight.

**Alternatives considered**:
- Strip UUIDs from the LLM response only (post-hoc). Rejected: the LLM wastes tokens processing/extending UUIDs when they could be used for actual content.
- Replace UUIDs with sequential `[1]` `[2]` labels (Pattern 1). Rejected: the user chose Pattern 4 (clean answer, no inline citations).

### Decision 2: Remove inline citation instruction from APIResponseGenerator signature

**Choice**: The `answer` output field description no longer asks for bracketed citations.

**Rationale**: The LLM faithfully follows signature instructions. If we don't ask for citations, it won't produce them.

### Decision 3: Simplify `validate_citations` — remove inline citation requirement

**Choice**: Stop checking for inline `[Name]` markers. Only validate that the explicit `citations` list contains known function/type names.

**Rationale**: The assertion was designed to catch cases where the LLM hallucinated fake function names. The `citations` list (produced by the DSPy output field) is sufficient for this. The inline check added no additional signal.

**Impact on tests**: Several tests explicitly tested the "missing inline citations" failure mode. These tests need updating:
- `test_validate_citations_missing_inline` — no longer applicable; remove or adapt
- `test_validate_citations_empty_answer` — inline check was the only failing condition; now it would pass vacuously
- `test_assertions_fail_logs_warning_and_returns_co_output` — previously `assertions_passed: False` due to missing inline citations; now `assertions_passed: True` since the citations list is valid
- `test_assertions_fail_does_not_call_fallback` — same change
- `test_assertions_fail_reports_both_citation_and_reference_issues` — answer has "I don't know the answer" with empty citations list → assertions_passed still False (reference check fails because "CreateNode" in question but not answer)

### Decision 4: Add UUID-stripping to `clean_response()` as defense-in-depth

**Choice**: Add a regex pattern matching standard UUID format to the existing `clean_response` function in `src/domain/services/prompt_builder.py`.

**Rationale**: Even though we're removing UUIDs from the prompt context, a defense-in-depth layer ensures that if any UUID-like pattern somehow appears in the final answer (e.g., from a chunk that embedded IDs in its own content), it gets cleaned.

**Pattern**: `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`

## Risks / Trade-offs

- **[Low] LLM may still produce `[Name]` style citations** from its training data even without being asked. The `clean_response()` defense-in-depth will not strip these — only UUIDs are stripped. If the LLM consistently produces `[FunctionName]` style markers, we may need to extend `clean_response()` with additional patterns. Mitigation: monitor first post-deployment iteration for any leak patterns.

- **[Low] `ContextAssembler` signature becomes slightly inconsistent** — it references `[chunk_id]` prefixes that no longer exist. However, this signature is currently unused (the pipeline passes chunks directly to `APIResponseGenerator`). Updated for correctness anyway.

- **[Low] Metrics may be slightly less precise** — `citation_accuracy` and `hallucination_rate` use both `_cited_names(answer)` (inline `[Name]` extraction) and the explicit `citations` field. With no inline citations, they rely solely on the `citations` field, which the DSPy model still produces. This is sufficient for quality monitoring.
