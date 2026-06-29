# Document Processing Lifecycle & Reliability

## Purpose

Ensure documents uploaded to the RAG pipeline are reliably processed to completion — even across server restarts — and that users receive timely progress feedback during the slowest stages (model loading, embedding). The system SHALL recover pending documents on startup, expose granular progress for long-running phases, pre-load the embedding model during warmup, and avoid redundant formatting work.

## Background / Investigation

### Profiling Results (axis com snippet.docx — 57 KB, 19 tables, 209 graph nodes)

| Stage | Duration (cold start) | Bottleneck |
|-------|----------------------|------------|
| Module imports (transitive) | ~8s | `sentence_transformers` loaded transitively |
| DOCX Parse | ~0.1s | — |
| Table Detect | ~0.001s | — |
| Convert | ~0.001s | — |
| Graph Build | ~0.01s | — |
| BM25 Index | ~0.01s | — |
| **Embedder Model Load** | **~16s** | `SentenceTransformer(…all-mpnet-base-v2)` |
| Batch Encode 209 texts | ~2.1s | `model.encode(…, batch_size=32)` |
| **Total** | **~26s** | — |

### Root Cause #1: No Pending Document Recovery

When a document is uploaded via `POST /api/v1/documents`, the endpoint creates a `Document` row with `status="pending"`, calls `trigger_document_processing(id)` via `asyncio.create_task(…)`, and returns the response immediately. If the server restarts (e.g., uvicorn `--reload`, deployment, crash), the in-memory `asyncio.Task` is lost and the document is stuck in `status="pending"` forever. The startup lifespan only loads *completed* documents from the `ApiDocIndex` table — it never scans for pending ones. Evidence: 45 of 47 documents in the database were stuck in `status="pending"` with `processing_step IS NULL`.

### Root Cause #2: No Progress During Model Loading

During the Embedding Index stage, the pipeline loads the `sentence-transformers/all-mpnet-base-v2` model (~500 MB) on first use, taking ~16 seconds on Apple Silicon with no progress update pushed to the database. The frontend polls `/api/v1/documents/{id}/status` every second but sees `step="extracting"` for the entire 16 seconds — making the app appear hung.

### Root Cause #3: Redundant `format_graph()` Call

`ApiEmbeddingIndex.add_graph()` calls `formatter.format_graph(graph, …)` again, even though `ApiDocPipelineManager.ingest_docx()` already formatted the same graph in Stage 4. This doubles string-formatting work for all nodes (~0.1s extra — minor but wasteful).

## Requirements

### Requirement 1: Pending document recovery on startup

The server SHALL scan for documents with `status="pending"` on startup and trigger their processing via `trigger_document_processing(id)`.

#### Scenario 1a: Pending documents found
- **GIVEN** one or more documents with `status="pending"` exist in the database
- **WHEN** the server starts up (lifespan phase)
- **THEN** the server SHALL call `trigger_document_processing(id)` for each pending document
- **THEN** each document SHALL transition through `status="processing"` to either `"completed"` or `"failed"`
- **THEN** the server SHALL log: `"Resumed N pending document(s) for processing"`

#### Scenario 1b: No pending documents
- **GIVEN** no documents with `status="pending"` exist
- **WHEN** the server starts up
- **THEN** startup SHALL proceed normally with no recovery action

#### Scenario 1c: Processing fails during recovery
- **GIVEN** a pending document whose file no longer exists on disk
- **WHEN** the recovery loop tries to process it
- **THEN** the document SHALL be marked `status="failed"` with `error_message="File not found: …"`
- **THEN** the recovery loop SHALL continue processing remaining documents

#### Scenario 1d: Pending document was already superseded
- **GIVEN** a document with `status="pending"` created before an already-completed re-processing run
- **WHEN** the recovery loop tries to process it
- **THEN** the stale-config check in `update_document_progress()` SHALL abort the stale task gracefully

### Requirement 2: Progress updates during model loading

The processing pipeline SHALL push a progress update to the database before entering any long-running or model-loading phase.

#### Scenario 2a: Embedding model loading phase
- **WHEN** the pipeline reaches the embedding index stage
- **THEN** the document status SHALL be updated to `step="indexing", message="Loading embedding model…"`
- **THEN** the frontend SHALL display this message after the next poll

#### Scenario 2b: Batch embedding phase
- **WHEN** the model is loaded and batch encoding begins
- **THEN** the document status SHALL be updated to `step="indexing", message="Embedding N chunks…"`
- **THEN** the `processed_chars` column SHALL update periodically (every 10 chunks or every 2 seconds, whichever comes first)

### Requirement 3: Model warmup at startup

The model warmup task launched during `lifespan` SHALL pre-load the embedding model so that the first document processing after startup does not pay the cold-start penalty.

#### Scenario 3a: Embedding model pre-loaded during warmup
- **WHEN** the server starts up
- **THEN** the warmup task SHALL include the embedding model
- **THEN** a subsequent `process_document_async` call SHALL NOT reload the model (the singleton check in `get_embedder()` returns the cached instance)

#### Scenario 3b: Warmup not yet complete when document arrives
- **GIVEN** the warmup task is still loading models
- **WHEN** a document upload triggers processing
- **THEN** `process_document_async` SHALL await the warmup task OR load the model directly (whichever completes first) — it MUST NOT deadlock

### Requirement 4: Remove redundant `format_graph()` call

The `ApiEmbeddingIndex` SHALL NOT call `format_graph()` when the graph content is already populated.

#### Scenario 4a: Graph already formatted
- **GIVEN** `graph.nodes[N].content` is non-empty for all nodes (graph was already formatted by the caller)
- **WHEN** `ApiEmbeddingIndex.add_graph()` is called
- **THEN** `add_graph()` SHALL skip the `formatter.format_graph()` call
- **THEN** the existing content SHALL be used directly

#### Scenario 4b: Graph not formatted (backward compatibility)
- **GIVEN** `graph.nodes[N].content` is empty (graph was NOT pre-formatted)
- **WHEN** `ApiEmbeddingIndex.add_graph()` is called
- **THEN** `add_graph()` SHALL call `formatter.format_graph()` as before, preserving backward compatibility for direct API consumers

## Implementation Notes

### Recovery loop location

Add recovery logic inside the ``lifespan`` context manager in
``src/api/main.py``, after the existing ``load_all_from_db()`` call (line
411).  Use the same ``async_session_maker`` session to query pending
documents.  Recovery SHALL be gated behind the same
``settings.api_docs_enabled`` flag.

Pseudo-code:

```python
# After existing load_all_from_db():
pending_result = await session.execute(
    select(Document).where(Document.status == "pending")
)
pending_docs = pending_result.scalars().all()
if pending_docs:
    logger.info("Resuming %d pending document(s) for processing", len(pending_docs))
    for doc in pending_docs:
        trigger_document_processing(doc.id)
```

### Progress update hook points

In ``src/domain/rag/api_docs/retrieval/embedding_index.py``, add progress
callbacks:

```python
async def add_graph(
    self, graph, formatter, ...,
    progress_callback: Callable[[str, str], Awaitable[None]] | None = None,
) -> None:
    if progress_callback:
        await progress_callback("indexing", "Loading embedding model…")
    embedder = await self._get_embedder()

    # Only format if content is not already populated (Requirement 4)
    needs_format = any(
        not node.content for node in graph.nodes.values()
    )
    if needs_format:
        formatter.format_graph(graph, interfaces, enums, error_codes, records=records)

    texts = [node.content for node in graph.nodes.values() if node.content]

    if progress_callback:
        await progress_callback(
            "indexing", f"Embedding {len(texts)} chunks…"
        )
    raw_embeddings = await embedder.embed_texts(texts)
    # ... rest unchanged
```

In ``src/domain/services/processor.py``, pass a lambda that calls
``update_document_progress()``:

```python
api_result = await _process_api_doc(
    document_id, file_path, doc_type, user_id=document.user_id,
    progress_callback=lambda step, msg: update_document_progress(
        document_id, step, msg,
        expected_config_id=expected_config_id,
    ),
)
```

### Warmup extension

In ``src/api/main.py``, extend the ``_load_models()`` warmup coroutine to
include the embedder:

```python
async def _load_models():
    """Pre-load ML models in background to reduce first-request latency."""
    try:
        from src.domain.services.embedding import get_embedder
        embedder = await get_embedder()
        logger.info("Embedding model warmup: dim=%d", embedder.get_dimension())
    except Exception as e:
        logger.warning("Embedding model warmup failed (non-fatal): %s", e)
    # ... existing LLM warmup code ...
```

## Test Strategy

| Test | Location | What it verifies |
|------|----------|-----------------|
| ``test_axis_com_processing_performance`` | ``tests/integration/test_processing_perf.py`` | Full pipeline timing budgets, domain object counts, query results |
| ``test_embedding_model_load_time`` | same file | Cold-start model load completes within 45s |
| Unit test for recovery loop | ``tests/unit/test_startup_recovery.py`` | Pending docs are picked up on startup, file-not-found docs fail gracefully |
| Unit test for progress hook | ``tests/unit/test_embedding_index_progress.py`` | Progress callback is invoked at correct stages |
| Unit test for redundant format | ``tests/unit/test_embedding_index_format.py`` | ``format_graph`` is NOT called when content is already populated |

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Rapid server restart re-triggers processing of in-flight docs | Low | Low | ``update_document_progress`` stale-config check aborts with old config_id |
| Warmup model loading delays server startup | Medium | Low | Warmup is async/non-blocking; server accepts requests immediately |
| Progress callback creates DB contention | Low | Low | ``update_document_progress`` already catches exceptions gracefully |
| Recovery loop delays startup with many pending docs | Low | Medium | Recovery is sequential but non-blocking (each doc gets its own Task) |

## Out of Scope

- Adding a persistent task queue (Celery / Redis Queue / SQS) — the in-process `asyncio.create_task` approach with startup recovery is sufficient for single-server deployments
- Frontend UI changes — the existing polling mechanism already shows progress; it only needs more granular updates from the backend
- Cross-encoder / DSPy model warmup — only the embedding model is in scope for pre-loading
