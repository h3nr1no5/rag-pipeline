## Context

The DSPy pipeline in `APIDocRAG.forward()` currently orchestrates four steps:

1. **QueryAnalyzer** (ChainOfThought) — rewrites user question into search queries
2. **Hybrid retrieval** (BM25 + FAISS + cross-encoder reranker) — retrieves chunks
3. **ContextAssembler** (ChainOfThought) — selects/reorders chunks from retrieval
4. **APIResponseGenerator** (ChainOfThought) — generates cited answer

Empirical testing shows: when DSPy is disabled (fallback path that skips steps 1 and 3), answers are correct and grounded. When DSPy is enabled, Qwen 1.5B hallucinates. The root cause is the 1.5B model's limited capacity for reliable multi-step reasoning — each LLM call compounds errors.

## Goals / Non-Goals

**Goals:**

- Eliminate DSPy-induced hallucinations by removing fragile multi-step LLM orchestration
- Preserve ChainOfThought reasoning trace display in the frontend
- Keep all existing response fields (answer, citations, confidence, reasoning_hint, etc.)

**Non-Goals:**

- No changes to the retrieval system (BM25, FAISS, reranker, link traversal)
- No changes to the response schema or API
- No changes to the fallback path
- No changes to configuration settings

## Decisions

### Decision 1: Remove QueryAnalyzer entirely (not just fallback on error)

The current code already falls back to the raw question when QueryAnalyzer throws. The fix hardcodes this behavior — removing the try/except and always using the raw question. Rationale: the QueryAnalyzer's output is actively harmful (generates bad queries that retrieve wrong chunks), not just occasionally failing.

### Decision 2: Remove ContextAssembler entirely

Same reasoning — the current fallback (all chunks) already works. The ContextAssembler with a 1.5B model drops relevant chunks, starving the generator of information it needs.

### Decision 3: Keep ChainOfThought for answer generation

The `APIResponseGenerator` remains a `ChainOfThought` predictor. This preserves the CoT reasoning trace that the frontend displays. The generator receives better context (all chunks, unfiltered by ContextAssembler) so its CoT reasoning is more accurate.

### Decision 4: Keep assertions as advisory

Citation/reference validation remains active as a logging/observability signal, but does not block answers. This matches the current advisory-only behavior.

## Risks / Trade-offs

- **[Minor performance]** Without QueryAnalyzer, only one search query is used instead of potentially multiple. The retriever casts a narrower net. Mitigation: the raw question is typically well-formed for retrieval, and the fallback path already proves this works well in practice.
- **[Minor noise]** Without ContextAssembler, the generator sees all retrieved chunks including potentially less-relevant ones. Mitigation: the reranker already prioritizes the most relevant chunks at the top, and the ChainOfThought generator can ignore irrelevant content.
