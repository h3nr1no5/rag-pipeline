## Why

LangChain RAG responses are hallucinating — the LLM makes up facts not present in the source documents. This erodes user trust and defeats the purpose of RAG. Analysis revealed multiple contributing factors: a prompt contradiction (model is told both "cite sources" and "never cite sources"), weak grounding instructions, no retrieval quality threshold (irrelevant chunks pass through with score=1.0), temperature too high for factual QA (0.5), and no verification that output claims are supported by source material.

## What Changes

- **Fix prompt contradiction**: The `no_verbatim` instruction always says "Never include '[Source N]' labels" even when `include_citations=True`, creating a direct conflict with the citation instruction
- **Remove "in your own words"**: This phrasing actively encourages the model to diverge from source text, a known anti-pattern for factual RAG
- **Lower default temperature**: Change from 0.5 to 0.1 for more deterministic, grounded generation
- **Add retrieval quality gating**: Apply a relevance threshold so low-quality or irrelevant chunks are filtered out before reaching the LLM. Switch to proper scoring via `retrieve_with_scores()` which is already implemented but unused
- **Add cross-encoder re-ranking**: After initial BM25+FAISS retrieval, re-rank results with a cross-encoder model for more accurate relevance judgment
- **Strengthen citation forcing**: Require mandatory inline `[Source N]` citations for every factual statement
- **Add claim verification**: Post-generation step that verifies each sentence in the response is supported by the source chunks, removing or flagging unsupported claims
- **Increase retrieval depth**: Retrieve more chunks (top_k=20) then filter to only the best, increasing chances of finding relevant content

## Capabilities

### New Capabilities
- `prompt-grounding`: Fix contradictory instructions, strengthen grounding constraints, enforce mandatory inline source citations for every factual claim
- `retrieval-quality-gating`: Apply relevance thresholds, switch to proper scoring, add cross-encoder re-ranking to ensure only relevant chunks reach the LLM
- `response-verification`: Post-generation verification pipeline that checks each claim against source chunks and removes or flags unsupported content

### Modified Capabilities
*(None — no existing specs to modify)*

## Impact

- **`src/domain/services/prompt_builder.py`**: Rewrite prompt instructions, citation logic, and `clean_response` post-processing
- **`src/domain/services/retrieval_langchain.py`**: Switch `retrieve()` to use proper scoring, apply relevance threshold, add cross-encoder re-ranker
- **`src/api/routes/query/routes.py`**: LangChain endpoints may need minor adjustments if retrieval interface changes
- **`src/domain/services/llm.py`**: Default temperature change in generation calls
- **`src/core/config.py`**: New config entries for re-ranker model, verification thresholds, temperature default
- **New file**: `src/domain/services/verification.py` — claim verification logic
- **Dependencies**: Add `sentence-transformers` cross-encoder model (or similar) for re-ranking; no new major dependencies for verification
