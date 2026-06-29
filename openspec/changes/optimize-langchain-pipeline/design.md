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
- Reduce LangChain query time from ~317s to under 180s (the frontend timeout) by halving the candidate pool from ~66 to ~30 docs
- Fix error propagation so frontend shows `st.error()` for transport/timeout failures instead of rendering errors as normal chat messages
- Show a clear "query timed out" message when the LangChain backend takes too long

**Non-Goals:**
- Increasing the 180s frontend timeout — the pipeline must be fast enough
- Rewriting the LangChain integration or switching to streaming
- Changing the cosine or LlamaIndex backends
- Modifying the LLM model or generation parameters (already fast at ~5s for 60 tokens)

## Decisions

### 1. Cross-encoder optimization: flash_attention_2 + bfloat16
**Why**: The current `Alibaba-NLP/gte-reranker-modernbert-base` model supports flash_attention_2 for faster attention computation (2-3x on CUDA sm80+) and bfloat16 for reduced memory bandwidth. Even on MPS, `torch.bfloat16` and SDPA (PyTorch's native scaled dot product attention) can provide meaningful speedups. These are purely configuration changes to `sentence_transformers.CrossEncoder` via `model_kwargs` — no model swap needed.

**Implementation**: Pass `model_kwargs={"torch_dtype": "bfloat16", "attn_implementation": "flash_attention_2"}` when initializing the cross-encoder. On unsupported hardware (MPS), `flash_attention_2` falls back gracefully, or we use `"sdpa"` instead for broader compatibility.

**Expected impact**: Reduces per-batch cross-encoder time from ~102s to potentially ~30-50s (hardware dependent), bringing total pipeline from ~317s to ~60-110s — well within the 180s frontend timeout.

**Risk**: On MPS, flash_attention_2 is unsupported → use `attn_implementation="sdpa"` as fallback, which still benefits from bfloat16. Verify bfloat16 dtype works at model load time.

### 2. Reduce candidate pool: `internal_top_k` from 20 → 10
**Why**: Currently BM25 returns 40 docs (`internal_top_k * 2`) and FAISS returns 40, producing ~66 unique candidates. By reducing `internal_top_k` to 10, BM25 and FAISS each return 20 docs → ~30 unique candidates. This halves cross-encoder work. Combined with flash_attention_2 + bfloat16, re-ranking drops from ~307s to ~30-75s.

**Risk**: Fewer candidates may occasionally miss relevant results. Mitigation: the hybrid BM25+FAISS ensemble already captures the most relevant docs in the top 10-20; reducing from 66 to 30 retains the high-precision candidates.

### 3. Error key in frontend exception handlers
**Why**: All 4 query functions (`query_sync`, `query_langchain_sync`, `query_llamaindex_sync`, `api_docs_query`) catch `Exception` and return an answer dict without an `"error"` key. The Chat page checks `if "error" in result` — which never triggers for transport errors. Adding `"error": "transport_error"` (for exceptions) and `"error": "http_error"` (for non-200 responses) ensures errors render via `st.error()`.

**Distinction**: `"transport_error"` means the connection failed (timeout, connection refused) — likely a server or network issue. `"http_error"` means the server responded with a non-200 status — likely a backend bug. Both set the `"error"` key with a specific value so the frontend can offer recovery suggestions.

### 4. No increase to 180s frontend timeout
**Why**: The user explicitly stated 180s is plenty. The pipeline optimization should bring the query under 180s. If occasional edge cases exceed the timeout, the improved error handling will show a clear message.

### 5. LangChain-specific timeout in backend
**Why**: As a secondary safeguard, the LangChain endpoint handler (`routes.py` lines 370-569) should use `asyncio.wait_for()` to enforce a backend-side timeout (e.g., 160s — slightly under the frontend's 180s). This prevents the backend from wasting compute on requests the frontend has already abandoned, and ensures a clean 500 response instead of an orphaned connection.

## Risks / Trade-offs

- **[Hardware dependency] Flash attention 2 requires CUDA**: On MPS (Apple Silicon), `flash_attention_2` is unsupported. → Mitigation: Use `attn_implementation="sdpa"` as fallback on unsupported hardware, which still benefits from bfloat16 and PyTorch's optimized attention. The bfloat16 optimization alone provides meaningful speedup on any device that supports it.
- **[Compatibility] bfloat16 model loading**: Some layers may not support bfloat16, causing load-time errors. → Mitigation: Verify at model load time; fall back to `torch.float16` or `float32` if bfloat16 fails. Wrap in try/except during `CrossEncoder.__init__`.
- **[Edge case] Query near 180s boundary**: Even with optimizations, some queries on slower hardware may still approach the 180s limit. → Mitigation: Backend `asyncio.wait_for()` at 160s ensures clean failure, and improved error handling shows a clear "query timed out — try rephrasing" message.
- **[Quality risk] Reduced candidate pool**: Dropping from 66 to ~30 candidates may occasionally miss relevant results. → Mitigation: Hybrid BM25+FAISS ensemble ensures diverse coverage; high-relevance docs rank near the top and are retained.
- **[Frontend] Error key changes affect all 4 backends**: The error key fix touches all query functions. → Mitigation: Only the exception handler return dicts change; no logic changes. Easy to review.
