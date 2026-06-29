## Context

The API docs RAG pipeline lives in `src/domain/rag/api_docs/` and is fully separate from the general RAG pipeline (`src/domain/services/`). It handles DOCX and PDF files containing COM interface documentation:

- **DOCX path**: `DocxParser` → `TableDetector` → `DocumentConverter` → `ChunkGraphBuilder` → `ChunkTextFormatter` → `ApiBm25Index` + `ApiEmbeddingIndex` → `HybridRetriever`
- **PDF path**: `PdfFallbackExtractor` → flat `ChunkNode`s (no structured extraction) → same indexing

The pipeline has never been formally spec'd or reviewed for correctness. Three critical defects were found during codebase exploration:

1. **Double format_graph bug** — `ApiEmbeddingIndex.add_graph()` re-formats chunk content using metadata-only fallback formatters, overwriting the rich domain-object formatted text set by the caller. Embeddings are computed on impoverished text (missing parameter names, return types, method lists).
2. **No response verification** — `_generate_answer()` feeds the LLM and returns raw output. No source-grounded check exists.
3. **No cross-encoder reranking** — The `HybridRetriever` goes straight from RRF fusion → link traversal → parent expansion, without a reranking step.

The general pipeline (`_retrieval.py`, `retrieval_langchain.py`, `retrieval_llamaindex.py`) already has cross-encoder reranking and response verification. The fix reuses those same shared modules rather than reimplementing them.

## Goals / Non-Goals

**Goals:**
- Fix the double `format_graph()` call so embeddings are computed on rich formatted text (parameter names, return types, interface details)
- Add cross-encoder reranking to the API docs `HybridRetriever.retrieve()` pipeline
- Add response verification to the API docs `_generate_answer()` flow
- Fix `LinkTraverser` mutable shared state race condition
- Fix error masking where LLM failures return 200 with a misleading error message
- All fixes must reuse existing shared modules (`CrossEncoderReRanker`, `ResponseVerifier`) — no new external dependencies

**Non-Goals:**
- Not refactoring the PDF fallback to do structured extraction (out of scope — the PDF path uses flat section nodes by design)
- Not adding streaming to the API docs query endpoint (separate change if desired)
- Not persisting the in-memory index from the deprecated ingest endpoint (low impact, endpoint is deprecated)
- Not modifying the confidence metric or score normalization (cosmetic, not a correctness issue)

## Decisions

### Decision 1: Pass domain objects through to `ApiEmbeddingIndex` (rather than removing format_graph call)

**Option A (chosen): Pass `interfaces`, `enums`, `error_codes` through the call chain → `manager.ingest_docx()` → `retriever.ingest_graph()` → `embedding_index.add_graph()` so the second `format_graph()` call has access to domain objects.**

**Option B (rejected): Remove the `format_graph()` call from `add_graph()` entirely.**

**Rationale:** Option B is simpler but breaks the API contract of `ApiEmbeddingIndex.add_graph()` — if someone calls it without pre-formatted content, the index is empty. Option A preserves the defensive re-format while fixing the root cause. The domain objects are already available in the manager; we thread them through the one additional call layer.

For the PDF path (`ingest_pdf()`), the graph is already formatted by `PdfFallbackExtractor` with raw content. No domain objects exist. We pass `None` for domain objects, and `text_formatter.format_graph(graph, None, None, None)` falls through to the existing metadata-only path — but since PDF nodes are `section`-kind with raw text, the metadata-only formatter uses the raw content directly (`_meta_method`/`_meta_parameter` are never reached). This is safe.

### Decision 2: Reuse shared `CrossEncoderReRanker` singleton

**Chosen:** Import `CrossEncoderReRanker` from `src.domain.services.retrieval_langchain` and add a rerank step in `HybridRetriever.retrieve()` between RRF fusion and link traversal.

**Rationale:** The general pipeline already has a lazy-loaded, thread-safe cross-encoder singleton. The same `gte-reranker-modernbert-base` model is suitable for COM domain text. Adding a dedicated singleton to the API docs package would duplicate model loading and memory.

**Integration:** The reranker takes `(query, [chunk_texts])` and returns relevance scores. The API docs hybrid retriever already has `chunk_ids` from RRF fusion; we map scores back to chunks, filter by `min_relevance_score`, then proceed to link traversal and parent expansion.

### Decision 3: Reuse shared `ResponseVerifier`

**Chosen:** Import `ResponseVerifier` from `src.domain.services.verification` and add a `verify()` call in `manager._generate_answer()` after `llm.generate()`.

**Rationale:** The `ResponseVerifier` already handles the cross-encoder verification, sentence splitting, unsupported sentence removal, and fallback message generation. No need to reimplement.

**Integration:** Pass the verifier the generated answer and the top N source chunks (as text). The verifier returns a `VerificationResult` with `verified_text` and `unsupported_sentences`. If `verified_text` is empty, return the fallback "I don't have enough information" message.

### Decision 4: Fix `LinkTraverser` race by using local state

**Chosen:** Change `_interface_name_to_id` from a `self` attribute to a local variable inside `traverse()`.

**Rationale:** `_interface_name_to_id` is rebuilt on every `traverse()` call and only used within that call. There is no reason for it to be instance state. Moving it to a local variable eliminates the race entirely at zero cost.

### Decision 5: Fix error masking by propagating exceptions

**Chosen:** Let the exception from `_generate_answer()` propagate to the route handler's existing `except Exception` block at `routes.py:193`, which already returns a proper 500.

**Rationale:** The route handler already has error handling. `_generate_answer()` swallowing the error and returning a string is what causes the misleading 200 response. The fix is to NOT catch `Exception` in `_generate_answer()` and instead let it raise. The `ImportError` for missing LLM module can remain caught with a specific log message, since that's a configuration issue, not a runtime error.

## Risks / Trade-offs

- **[Risk]** Cross-encoder reranking adds latency (~100-500ms per top-k batch) to every query.
  → **Mitigation:** Rerank only the top 20 candidates (matching the general pipeline's `internal_top_k` pattern). The model is already loaded as a singleton.

- **[Risk]** Response verification may over-filter technical COM descriptions where short sentences like "HRESULT" or "Returns S_OK" fail similarity against a verbose source chunk.
  → **Mitigation:** Use the existing configurable `verification_similarity_threshold` (default 0.55) — the same threshold used by the general pipeline. It was tuned on technical documentation.

- **[Risk]** Passing domain objects through `ingest_graph()` changes the API of `HybridRetriever` and `ApiEmbeddingIndex`.
  → **Mitigation:** The parameters are optional (`None` defaults). All existing call sites (`ingest_pdf()`, `load_from_db()`) pass `None` and get current behavior.

- **[Trade-off]** The PDF fallback path receives no cross-encoder benefit from improved embedding text (it has no domain objects). This is acceptable because PDF is a fallback path; the primary DOCX path gets the full fix.
