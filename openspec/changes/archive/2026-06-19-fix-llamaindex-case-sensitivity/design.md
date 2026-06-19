## Context

The LlamaIndex RAG backend uses a `HybridRetriever` that fuses dense (embedding similarity) and sparse (BM25 keyword) retrieval via Reciprocal Rank Fusion (RRF). Two bugs in this pipeline cause the backend to fail for a significant class of queries:

1. **BM25 is case-sensitive**: `str.split()` tokenization preserves original case in both the BM25 corpus index and the query. Lowercase "llm" never matches uppercase "LLM" in the BM25 corpus, so BM25 contributes zero results. The dense embedding path partially compensates, but RRF fusion's rank-based weighting means the dense signal is diluted. The 1.5B quantized LLM then confuses the case mismatch between the question ("llm") and the source text ("LLM") and defaults to "I don't have enough information."

2. **Source boundary markers are conditional**: `_apply_chat_template()` in `llm.py` relies on finding `\n[Source ` to split the prompt into system and user messages. But `build_prompt()` in `prompt_builder.py` omits `[Source N]:` labels when `include_citations=False`. Without the boundary marker, the entire prompt (instructions + context + question) is treated as a single user message. The model cannot distinguish instructions from source material, and defaults to refusing to answer.

## Goals / Non-Goals

**Goals:**
- BM25 retrieval in the LlamaIndex hybrid retriever matches acronyms regardless of case (e.g., "llm" ↔ "LLM")
- The prompt template split always finds the `[Source N]` boundary, regardless of citation preference
- All three backends (cosine, LangChain, LlamaIndex) handle case variation in queries consistently
- The `include_citations=False` feature still works — the citation instruction is removed from the system prompt, and `clean_response()` still strips `[Source N]` from the output

**Non-Goals:**
- No changes to the cosine or LangChain backends (they don't use BM25 or this prompt split mechanism)
- No changes to the BM25 algorithm itself (only token normalization)
- No changes to the cross-encoder reranker or RRF fusion logic
- No new configuration options

## Decisions

### Decision 1: Lowercase normalization for BM25 (not stemming or lemmatization)

**Choice**: Normalize both corpus documents and query tokens to lowercase using `str.lower().split()`.

**Alternatives considered**:
- *Stemming (e.g., Porter stemmer)*: Overkill for acronym matching, adds a dependency, and could collapse distinct terms (e.g., "policy" ↔ "police").
- *Lemmatization*: Heavyweight NLP pipeline for a simple case-matching problem.
- *Case-insensitive BM25 implementation*: Would require forking or monkey-patching `rank_bm25`, which is fragile.

**Rationale**: Lowercasing is the minimal, zero-dependency change that exactly fixes the reported bug. The LlamaIndex backend's BM25 index is rebuilt on every retrieval (`_build_bm25` is called in `__init__`), so the change is self-contained within `HybridRetriever`. The only two code paths affected are `_build_bm25()` (corpus tokenization) and `_aretrieve()` (query tokenization for BM25 scoring).

### Decision 2: Always include `[Source N]` labels, only make citation instruction conditional

**Choice**: `build_prompt()` always prepends `[Source N]:` labels to context chunks. The `include_citations` flag controls only whether the citation instruction appears in the system prompt and whether `clean_response()` strips `[Source N]` from the output.

**Alternatives considered**:
- *Fix `_apply_chat_template()` to use a different splitting mechanism*: Could split on `\n\nQuestion:` instead. But this is more fragile — the template format could change, and it doesn't benefit from the semantic clarity of source labels.
- *Inject a hidden boundary marker*: e.g., `\n---BOUNDARY---\n` — adds a magic string that could leak into the output.

**Rationale**: Adding `[Source N]` labels unconditionally is the simpler, more robust fix. The labels are harmless when citations are disabled — `clean_response()` already strips them from the output. The labels provide the model with source structure regardless of citation preference, which may improve answer quality. This approach also matches the LangChain backend's behavior, which always uses source labels internally and strips them at the response layer.

**Spec impact**: The `response-formatting` spec requirement "Citation instruction conditional on `include_citations`" must be updated. The scenario for `include_citations=False` changes from "context chunks SHALL be provided without `[Source N]` labels" to "context chunks SHALL always have `[Source N]` labels, but the citation instruction SHALL be omitted from the system prompt."

### Decision 3: No changes to the response-formatting spec's `clean_response` behavior

`clean_response()` already has the correct behavior: it unconditionally strips `[Source N]` from output when `include_citations=False`. The fix to `build_prompt()` means `[Source N]` labels are now always present in the context (and thus potentially in the LLM output), but `clean_response()` already handles this correctly. No spec change needed for `clean_response`.

## Risks / Trade-offs

- **[Low] LLM may produce `[Source N]` in output when citations disabled**: If the LLM reproduces source labels in its answer despite no citation instruction, `clean_response()` will strip them. The user won't see them in the response. No user-facing impact.

- **[Low] BM25 lowercasing changes IDF statistics**: Lowercasing merges tokens that were previously distinct (e.g., "LLM" and "llm" now share a single corpus frequency). This slightly reduces BM25's ability to distinguish between these forms, but since case variation in the same term shouldn't carry semantic weight, this is strictly an improvement.

- **[None] No degradation when citations enabled**: The `include_citations=True` path already includes `[Source N]` labels — no behavior change.

## Migration Plan

No migration needed. This is a pure code fix with no data migration, no configuration changes, and no API contract changes. The change is deployable as a single commit.

## Open Questions

None. Both bugs are well-understood with minimal, targeted fixes.
