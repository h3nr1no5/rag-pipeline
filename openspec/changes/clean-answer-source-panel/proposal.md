## Why

The api-docs RAG pipeline leaks UUID chunk identifiers into generated answers, producing noisy text like `[41205821-9d08-...] GetMaterial takes three parameters`. This degrades readability without improving answer quality — users don't need inline citations when the source panel already provides full attribution. Industry RAG best practice (Pattern 4: clean answer + source panel, used by Notion AI, Glean, Cursor) keeps answers clean and moves attribution to a separate sources expander.

## What Changes

- **Remove UUID prefix** from chunk context passed to the DSPy LLM — stop sending `[chunk_id]` labels
- **Remove inline citation instruction** from DSPy signature — the LLM is no longer asked to output `[Name]` markers
- **Simplify assertions** — remove `validate_citations` check that required inline bracket citations; keep `check_question_references` which validates by plain-text matching
- **Add defense-in-depth** — UUID regex stripping in cleanup functions for any residual leaks
- **No changes** to the Sources expander UI (already works correctly) or the chunking/indexing pipeline

## Capabilities

### New Capabilities

*(None — this is an implementation-only change to the answer generation pipeline, not a new capability.)*

### Modified Capabilities

*(None — no spec-level behavior changes; the answer format is an implementation detail, not a spec-level requirement.)*

## Impact

- **`src/domain/rag/api_docs/pipeline/module.py`** — `_format_chunks()` removes UUID prefix; assertion calls updated
- **`src/domain/rag/api_docs/pipeline/signatures.py`** — `ContextAssembler` and `APIResponseGenerator` signatures updated to remove citation instructions
- **`src/domain/rag/api_docs/pipeline/assertions.py`** — `validate_citations()` simplified (inline citation requirement removed); `extract_cited_names` and `_CITATION_RE` may be removed
- **`src/api/helpers/clean_response.py`** (or equivalent cleanup) — UUID-stripping regex added as defense-in-depth
- **DSPy test expectations** — any tests asserting `[uuid]` in answers need updating
- **No breaking changes** to the API contract — the `sources` field in the response is unchanged
