## 1. Configuration

- [x] 1.1 Add `api_docs_dspy_enabled: bool = Field(default=True, description=...)` to settings in `src/core/config.py`
- [x] 1.2 Add `API_DOCS_DSPY_ENABLED=true` to `.env.example`
- [x] 1.3 Store `self._dspy_enabled` in `ApiDocPipelineManager.__init__()` by reading `get_settings().api_docs_dspy_enabled`

## 2. Refactor Manager Query Path

- [x] 2.1 Rename current `query()` body to `_query_fallback()` — takes `(retriever, graph, query_text, top_k, rerank_k)` as explicit params, returns `ApiDocQueryResponse`
- [x] 2.2 Implement new `query()` method with DSPy/fallback dispatch — reads `self._dspy_enabled`, calls `_query_dspy()` or `_query_fallback()`, wraps in circuit-breaker try/except
- [x] 2.3 Implement `_query_dspy()` method — instantiates `APIDocRAG(retriever)`, calls `forward(question=query_text, top_k=top_k)`, maps result dict to `ApiDocQueryResponse`

## 3. Output Mapping from DSPy Dict to ApiDocQueryResponse

- [x] 3.1 Implement `_build_dspy_response(result: dict, graph: ChunkGraph, latency_ms: int) -> ApiDocQueryResponse` helper that maps the `APIDocRAG.forward()` output keys to `ApiDocQueryResponse` fields per the specification table
- [x] 3.2 Implement chunk-to-source resolution: for each `(chunk_id, score)` in `retrieved_chunks`, look up the node in `graph.nodes[chunk_id]` and build an `ApiDocSource` with content, metadata (interface_name, function_name, kind)
- [x] 3.3 Call `ResponseVerifier.verify()` on the DSPy-generated answer, populate `unsupported_sentences`

## 4. Circuit Breaker

- [x] 4.1 Wrap `_query_dspy()` call in `query()` with try/except — on exception, log a warning with traceback and fall back to `_query_fallback()` using the same retriever and graph
- [x] 4.2 Verify that when both DSPy and fallback fail, the exception propagates naturally to the route handler

## 5. Test

- [x] 5.1 Update existing API docs manager tests to cover DSPy-enabled path — mock `APIDocRAG`, verify `forward()` is called and output is mapped correctly
- [x] 5.2 Add test for DSPy-to-fallback circuit breaker — mock `APIDocRAG.forward()` to raise, verify `_query_fallback()` is called
- [x] 5.3 Add test for `api_docs_dspy_enabled=false` — verify DSPy path is skipped entirely
- [x] 5.4 Add test for output mapping correctness — verify that chunk IDs from `retrieved_chunks` resolve to correct `ApiDocSource` objects via the graph
- [x] 5.5 Run `uv run pytest tests/unit/ tests/integration/ -v` — all existing tests pass

## 6. Verification

- [x] 6.1 Run `uv run ruff check src/domain/rag/api_docs/` — no lint errors
- [x] 6.2 Run `uv run mypy src/domain/rag/api_docs/` — no type errors
- [x] 6.3 Run integration test for API doc query end-to-end with DSPy enabled — verify valid response returned
- [x] 6.4 Set `API_DOCS_DSPY_ENABLED=false`, run integration test — verify fallback path returns identical response shape

## 7. Bug Fixes

- [x] 7.1 Diagnose root cause of "could not find relevant information" responses
- [x] 7.2 Fix: wrap module.forward() in asyncio.to_thread() in manager.py
- [x] 7.3 Verify fix with tests
