## Context

The RAG pipeline processes uploaded DOCX documents through a 5-stage pipeline (parse → detect → convert → chunk → index) in an `asyncio.create_task` background task. Profiling against the production fixture `axis com snippet.docx` (57 KB, 19 tables, 209 graph nodes) reveals three root causes for unreliable processing:

1. **No recovery on restart**: 45/47 documents are stuck in `status="pending"` because the in-process `asyncio.Task` is lost on server restart. The `lifespan` handler only loads completed documents from the `ApiDocIndex` table.
2. **No progress during model load**: The embedding model (`all-mpnet-base-v2`, ~500 MB) takes ~16s to load from cold cache, with zero database updates — the frontend sees `step="extracting"` the entire time.
3. **Redundant work**: `ApiEmbeddingIndex.add_graph()` calls `formatter.format_graph()` again even though `ApiDocPipelineManager.ingest_docx()` already formatted the graph.

Cold-start total is ~26s (module imports ~8s + model load ~16s + encoding ~2s). Cached runs complete in ~0.23s — model loading is the sole bottleneck.

## Goals / Non-Goals

**Goals:**
- Recover pending documents on server startup so they complete without manual intervention
- Push progress updates to the database during model loading and batch embedding phases
- Pre-load the embedding model during startup warmup (alongside the existing LLM warmup)
- Remove the redundant `format_graph()` call in `ApiEmbeddingIndex.add_graph()`
- Add a performance regression test with timing budgets for the full pipeline

**Non-Goals:**
- Persistent task queues (Celery, Redis Queue, SQS) — in-process `asyncio.create_task` with startup recovery is sufficient for single-server deployments
- Frontend UI changes — the existing polling mechanism already displays progress; it just needs more granular backend updates
- Cross-encoder or DSPy model warmup — only the embedding model is in scope
- Database schema changes — existing `Document.status`, `processing_step`, `processed_chars`, and `error_message` columns suffice

## Decisions

### Decision 1: Lifespan recovery loop (not a separate worker)

- **Choice**: Query pending documents in the `lifespan` context manager after `load_all_from_db()`, then call `trigger_document_processing()` for each
- **Rationale**: Simplest implementation with zero new infrastructure. The `Document.status` column is already the source of truth. Each pending doc gets its own `asyncio.create_task`.
- **Alternatives considered**: A background polling worker would add complexity and latency. An external queue would require Redis/SQS.
- **Gating**: Gated behind `settings.api_docs_enabled` (same as existing loading logic)
- **Staleness protection**: Existing `update_document_progress()` already has a `stale_config` check that aborts processing when the document was superseded

### Decision 2: Progress callback injection (not DB polling)

- **Choice**: Add an optional `progress_callback: Callable[[str, str], Awaitable[None]]` parameter to `ApiEmbeddingIndex.add_graph()`. Wire it in `process_document_async()` via a lambda that calls `update_document_progress()`.
- **Rationale**: Callback-based approach is decoupled — `ApiEmbeddingIndex` doesn't need to know about the database. The same hook could drive WebSocket/SSE updates later without changing the index code.
- **Alternatives considered**: Polling the embedding index for state would be fragile. Direct DB coupling in the index would violate separation of concerns.

### Decision 3: Embedding model warmup in existing `_load_models()` coroutine

- **Choice**: Extend the existing `_load_models()` background task in `src/api/main.py` to call `get_embedder()` after the LLM warmup
- **Rationale**: Reuses the existing async warmup pattern. The singleton in `get_embedder()` means warmup populates the cache, and subsequent calls return immediately.
- **Failure handling**: Warmup failures are logged as warnings (non-fatal). The document pipeline loads the model on-demand as a fallback.

### Decision 4: Content-empty check for format skip (not a flag)

- **Choice**: Check `any(not node.content for node in graph.nodes.values())` to decide whether `format_graph()` is needed
- **Rationale**: Zero API surface change — no new parameter, no new flag. Backward-compatible: if someone calls `add_graph()` directly without pre-formatting, the content is empty and formatting proceeds as before.
- **Alternatives considered**: A `skip_format: bool` parameter would be explicit but clutters the API. A separate method would be redundant.

## Risks / Trade-offs

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Rapid server restart re-triggers in-flight docs | Low | Low (duplicate work, not corruption) | `stale_config` check aborts with old config_id |
| Warmup delays server startup startup time | Medium | Low | Warmup is non-blocking `asyncio.create_task`; server accepts requests immediately |
| Progress callback creates DB contention under high load | Low | Low | `update_document_progress()` already catches and logs exceptions gracefully |
| Recovery loop delays startup with many pending docs | Low | Medium | Sequential query but each doc gets its own async task; large batches could be batched if needed |
| Redundant format removal misses edge case (empty content that should be formatted) | Low | Low | Backward-compatible fallback: if any node has empty content, formatting runs |

## Migration Plan

1. Implement in order: format skip (safe, minimal) → progress callback → warmup extension → recovery loop
2. Add unit tests alongside each fix
3. Run existing test suite: `uv run pytest -v -m "not slow"`
4. Run performance test: `uv run pytest tests/integration/test_processing_perf.py -v --timeout=120`
5. Verify with lint (`ruff check .`) and typecheck (`mypy src/`)

No deployment or rollback complexity — all changes are runtime fixes. Rollback is `git revert`.
