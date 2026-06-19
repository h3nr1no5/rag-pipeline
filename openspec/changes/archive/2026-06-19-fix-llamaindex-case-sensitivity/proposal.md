## Why

The LlamaIndex RAG backend produces unreliable answers when users ask questions with lowercase acronyms (e.g., "what is llm?" returns "I don't have enough information" while "what is LLM?" works correctly). This is caused by two interacting bugs: BM25 case sensitivity causing retrieval failure for lowercase queries, and missing source boundary markers breaking prompt assembly when citations are disabled. Together these make the LlamaIndex backend unreliable for a significant class of real-world queries.

## What Changes

- **Fix BM25 case sensitivity**: Normalize both document and query tokens to lowercase in the LlamaIndex hybrid retriever so BM25 matches acronyms regardless of case
- **Always label source boundaries**: Remove the conditional omission of `[Source N]` labels — context chunks always receive labels, only the citation instruction in the system prompt remains conditional on `include_citations`
- **Update response-formatting spec**: The existing requirement that `[Source N]` labels are omitted when `include_citations=False` is changed to always include labels
- No API changes, no new endpoints, no dependency changes

## Capabilities

### New Capabilities

None — this is a bug fix within existing capabilities.

### Modified Capabilities

- `response-formatting`: The requirement "Citation instruction conditional on include_citations" changes its `include_citations=False` scenario — context chunks SHALL always have `[Source N]` labels, but the citation instruction in the system prompt SHALL remain conditional

## Impact

- **`src/domain/services/retrieval_llamaindex.py`**: BM25 token normalization (lowercasing) in `_build_bm25()` and BM25 section of `_aretrieve()`
- **`src/domain/services/prompt_builder.py`**: Always prepend `[Source N]:` labels to context chunks regardless of `include_citations` flag
- **Specs**: `openspec/specs/response-formatting/spec.md` — update the `include_citations=False` scenario to remove the "SHALL NOT have `[Source N]` labels" clause
