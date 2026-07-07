## Context

The API doc RAG pipeline has two independent code paths for answer generation:

**Current query flow (`ApiDocPipelineManager.query()`):**
```
query_text → retriever.retrieve() → build_sources() → _generate_answer() → ApiDocQueryResponse
                                                          │
                                                          └─► simple hardcoded prompt → LLM
```

**DSPy pipeline (`APIDocRAG.forward()`)** — built but not called:
```
query_text → QueryAnalyzer → multi-query retrieval → ContextAssembler → ResponseGenerator → assertions → dict
                                                                                                  │
                                                                                                  └─► fallback Predict
```

The DSPy pipeline adds structured query analysis, LLM-guided context assembly, ChainOfThought reasoning, citation validation with retry, and structured output extraction — none of which the current prompt-based path provides.

The `_generate_answer()` fallback (line 428 of `manager.py`) is explicitly documented as "fallback when APIDocRAG is unavailable" but no code ever tries to use the module.

## Goals / Non-Goals

**Goals:**
- Make `APIDocRAG.forward()` the primary generation path in `manager.query()` when DSPy is available
- Preserve the current prompt-based generation as a configurable fallback
- Map the DSPy module's rich output (answer, citations, relevant_functions, relevant_types, confidence, assertions_passed) into the existing `ApiDocQueryResponse` schema
- Add a configuration toggle to disable DSPy and revert to prompt-only (e.g., for debugging)
- Add response verification (`ResponseVerifier`) to the DSPy-generated answer (same as the fallback path)
- Pass the `HybridRetriever` from the manager's per-document store to the `APIDocRAG` module

**Non-Goals:**
- Not modifying the DSPy signatures, assertions, or metrics themselves
- Not running DSPy compilation/optimization (MIPROv2, BootstrapFewShot) — deferred
- Not changing the API route layer (`routes.py` queries are already correct)
- Not storing `APIDocRAG` instances persistently (created per-request from the stored retriever)
- Not changing the existing 3 RAG backends or their query paths

## Decisions

### 1. Integration Point: Replace `_generate_answer()` Call in `query()`

**Problem**: The `query()` method does retrieval then calls `_generate_answer()` with sources. The DSPy module does retrieval internally (multi-query from query analysis). These two retrieval patterns conflict.

**Decision**: Split the `query()` method into two paths at the method level:

```
async def query(...):
    info = self._indexed_docs[(user_id, document_id)]
    retriever = info["retriever"]

    if self._dspy_enabled:
        return await self._query_dspy(retriever, query_text, top_k, rerank_k)
    else:
        return await self._query_fallback(retriever, query_text, top_k, rerank_k)
```

The current `query()` body becomes `_query_fallback()`. A new `_query_dspy()` method wraps the DSPy path. This keeps both paths readable and independently testable.

**Alternatives considered:**
- *Call APIDocRAG inside `_generate_answer` as a try-first* → rejected: the DSPy module consumes a `HybridRetriever`, not `list[ApiDocSource]`. The integration point must be before source building, not after.
- *Pass retriever to `_generate_answer` and let it decide* → rejected: mixes responsibilities; `_generate_answer` is a simple prompt wrapper, not an orchestrator.
- *Store APIDocRAG instances in `_indexed_docs`* → rejected: DSPy modules hold LM references and are not serializable; creating them per-request from the stored retriever is simpler and avoids state sync issues.

### 2. DSPy Module Lifecycle: Per-Request Instantiation

**Decision**: Create a new `APIDocRAG(retriever)` instance on each DSPy-mode query. The `HybridRetriever` and the underlying BM25/embedding indices are read-only once built, so sharing is safe. The LM adapter is a singleton, so there's no per-request LM creation cost.

```python
async def _query_dspy(self, retriever, query_text, top_k, rerank_k):
    from src.domain.rag.api_docs.pipeline.module import APIDocRAG

    module = APIDocRAG(hybrid_retriever=retriever)
    result = module.forward(question=query_text, top_k=top_k)
    # ... map result to ApiDocQueryResponse ...
```

**Rationale**: APIDocRAG init is lightweight (stores a reference + creates three DSPy predictors). The heavy work (LM calls) happens in `forward()`. Per-request creation avoids serialization concerns and keeps the manager stateless with respect to DSPy.

### 3. Output Mapping: APIDocRAG dict → ApiDocQueryResponse

The APIDocRAG `forward()` returns a dict with these keys. The mapping to `ApiDocQueryResponse`:

| APIDocRAG output | ApiDocQueryResponse field | Notes |
|---|---|---|
| `answer` | `.answer` | Direct pass-through |
| `citations` | `.citations` | Direct pass-through |
| `relevant_functions` | `.relevant_functions` | Direct pass-through |
| `relevant_types` | `.relevant_types` | Direct pass-through |
| `confidence` | `.confidence` | DSPy-generated confidence (0-1); replaces score-based heuristic |
| `retrieved_chunks` | `.sources` | Map from (chunk_id, score) tuples to `ApiDocSource` objects. Need to look up chunk content/metadata from the graph. |
| `assertions_passed` | (not in schema) | Logged for observability |
| `used_fallback` | (not in schema) | Logged for observability |

**Chunk-to-source mapping**: The `retrieved_chunks` list contains `(chunk_id, score)` tuples. To build `ApiDocSource` objects, `_query_dspy` needs access to the `ChunkGraph` to look up content and metadata. The graph is already stored in `_indexed_docs` alongside the retriever.

**Response verification**: Run `ResponseVerifier.verify()` on the DSPy-generated answer against source chunks, same as the fallback path. This catches any hallucinations the DSPy assertions missed.

### 4. Configuration: `api_docs_dspy_enabled` Setting

**Decision**: Add a boolean setting `api_docs_dspy_enabled` to `config.py`, defaulting to `true`.

```python
# In src/core/config/settings.py or equivalent
api_docs_dspy_enabled: bool = Field(
    default=True,
    description="Use DSPy pipeline for API doc answer generation. "
    "Set to false to fall back to prompt-based generation.",
)
```

Add to `.env.example`:
```
API_DOCS_DSPY_ENABLED=true
```

When `false`, the manager uses the original `_query_fallback` path. When `true` (default), uses `_query_dspy`. If the DSPy module fails at runtime (exception in `forward()`), it falls back to `_query_fallback` automatically and logs a warning.

### 5. Manager State: Graph Reference in DSPy Path

The `_query_dspy` method needs the `ChunkGraph` to build `ApiDocSource` objects from chunk IDs. The graph is already in `_indexed_docs`:

```python
info = self._indexed_docs[(user_id, document_id)]
retriever, graph = info["retriever"], info["graph"]
```

This is the same `info` dict that `_query_fallback` already accesses. No additional storage required.

### 6. Fallback Behavior (Circuit Breaker)

If any step in `_query_dspy` raises an exception (LM unavailable, DSPy module error, assertion crash):

```python
try:
    return await self._query_dspy(...)
except Exception:
    logger.warning("DSPy pipeline failed — falling back to prompt generation", exc_info=True)
    return await self._query_fallback(...)
```

This ensures the API never returns a 500 due to DSPy issues. The fallback is silent to the user — only logs reveal which path was taken.

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|-----------|
| DSPy module exceptions crash the query | API returns 500 | Circuit-breaker catches all exceptions → silent fallback to prompt-based generation |
| DSPy-generated answer is worse than prompt baseline | User gets lower quality | A/B comparison possible via `api_docs_dspy_enabled=false`; launch with both paths monitored |
| Per-request APIDocRAG creation adds latency | ~10-50ms overhead | Acceptable (init is lightweight); if problematic, cache instances by document_id |
| Two query paths diverge behaviorally (citations, sources) | Users see different response shapes | The response schema is identical; only internal generation quality differs |
| DSPy uses `asyncio.run()` inside `forward()` (blocking) | Blocks event loop on long generations | This is an existing issue in the DSPy module (module.py line 157). Mitigation: the LM call inside `asyncio.run()` blocks the calling thread. The module is already shipped with this pattern — this change doesn't introduce new blocking. Future work: make `forward()` async. |
