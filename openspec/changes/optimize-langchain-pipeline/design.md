## Context

The LangChain RAG pipeline currently takes ~317 seconds per query, dominated by the cross-encoder re-ranker (`Alibaba-NLP/gte-reranker-modernbert-base`, ~395M params) which scores 66 candidate documents in 3 batches at ~102s/batch. Meanwhile, the frontend has a hard 180s timeout on `requests.post()` calls. This means every LangChain query exceeds the timeout and users see a generic "Error: Unable to process request" message — which the Chat page renders as a normal assistant message because `query.py` never sets an `"error"` key in exception handlers.

The pipeline flow is:
```
BM25 (k=40) ──→ 40 docs ──┐
                           ├──→ 66 unique → Cross-encoder → 20 → final 5
FAISS (k=40) ─→ 40 docs ──┘    307s (3×102s)     ↑
```

The other backends (cosine ~2s, LlamaIndex ~5s) complete well within the timeout.

## Goals / Non-Goals

**Goals:**
- Reduce LangChain query time from ~317s to under 180s (the frontend timeout)
- Replace the oversized cross-encoder with a model ~20x smaller
- Reduce the number of candidates scored by the cross-encoder
- Fix error propagation so frontend shows `st.error()` for transport/timeout failures instead of rendering errors as normal chat messages
- Show a clear "query timed out" message when the LangChain backend takes too long

**Non-Goals:**
- Increasing the 180s frontend timeout — the pipeline must be fast enough
- Rewriting the LangChain integration or switching to streaming
- Changing the cosine or LlamaIndex backends
- Modifying the LLM model or generation parameters (already fast at ~5s for 60 tokens)

## Decisions

### 1. Cross-encoder: `cross-encoder/ms-marco-MiniLM-L-6-v2`
**Why**: ~22M params vs ~395M for the current model. MiniLM-L-6 is a proven model for re-ranking tasks with ~10-20x faster inference. No new dependencies — same `sentence_transformers.CrossEncoder` API, just a model name change in settings.

**Alternatives considered**: `Alibaba-NLP/gte-reranker-modernbert-base` (current — too slow), `cross-encoder/ms-marco-TinyBERT-L-2` (even smaller but quality loss), Cohere rerank API (external dependency, latency, cost).

### 2. Reduce candidate pool: `internal_top_k` from 20 → 10
**Why**: Currently BM25 returns 40 docs (`internal_top_k * 2`) and FAISS returns 40, producing ~66 unique candidates. By reducing `internal_top_k` to 10, BM25 and FAISS each return 20 docs → ~30 unique candidates. This halves cross-encoder work. Combined with the faster model, re-ranking drops from 307s to ~5-10s.

**Risk**: Fewer candidates may occasionally miss relevant results. Mitigation: the hybrid BM25+FAISS ensemble already captures the most relevant docs in the top 10-20; reducing from 66 to 30 retains the high-precision candidates.

### 3. Error key in frontend exception handlers
**Why**: All 4 query functions (`query_sync`, `query_langchain_sync`, `query_llamaindex_sync`, `api_docs_query`) catch `Exception` and return an answer dict without an `"error"` key. The Chat page checks `if "error" in result` — which never triggers for transport errors. Adding `"error": "transport_error"` (for exceptions) and `"error": "http_error"` (for non-200 responses) ensures errors render via `st.error()`.

**Distinction**: `"transport_error"` means the connection failed (timeout, connection refused) — likely a server or network issue. `"http_error"` means the server responded with a non-200 status — likely a backend bug. Both set the `"error"` key with a specific value so the frontend can offer recovery suggestions.

### 4. No increase to 180s frontend timeout
**Why**: The user explicitly stated 180s is plenty. The pipeline optimization should bring the query under 180s. If occasional edge cases exceed the timeout, the improved error handling will show a clear message.

### 5. LangChain-specific timeout in backend
**Why**: As a secondary safeguard, the LangChain endpoint handler (`routes.py` lines 370-569) should use `asyncio.wait_for()` to enforce a backend-side timeout (e.g., 160s — slightly under the frontend's 180s). This prevents the backend from wasting compute on requests the frontend has already abandoned, and ensures a clean 500 response instead of an orphaned connection.

## Risks / Trade-offs

- **[Quality risk] MiniLM-L-6 re-ranking accuracy**: MiniLM is less accurate than the modernbert model. → Mitigation: MiniLM-L-6 is well-established for MS MARCO passage ranking. The cross-encoder acts as a second-pass filter over top candidates; even with slightly lower accuracy, the hybrid BM25+FAISS first pass ensures relevant docs are in the pool.
- **[Edge case] Query near 180s boundary**: If optimizations aren't enough, some queries may still time out. → Mitigation: Backend `asyncio.wait_for()` at 160s ensures clean failure, and improved error handling shows a clear "query timed out — try rephrasing" message.
- **[Compatibility] Cross-encoder model download**: New model needs to be downloaded on first use (~80MB). → Mitigation: Same as existing models; `HF_HUB_OFFLINE=1` can skip if pre-cached.
- **[Frontend] Error key changes affect all 4 backends**: The error key fix touches all query functions. → Mitigation: Only the exception handler return dicts change; no logic changes. Easy to review.
