## Context

The asyncio audit revealed a critical cross-event-loop bug in the DSPy RAG pipeline and several recurring async anti-patterns across the backend:

- **DSPy pipeline** (`module.py` → `manager.py` → `lm_adapter.py`): `APIDocRAG.forward()` is called via `asyncio.to_thread()` (off the main event loop), then inside that thread calls `asyncio.run()` to bridge back to async — creating a new event loop per invocation. The LM adapter follows the same pattern. Any async resource shared across loops (aiosqlite connections, asyncio.Lock, singleton embedders) would crash with `RuntimeError: attached to a different loop`. Currently works by accident because the embedder is loaded synchronously.
- **Processor** (`processor.py`): Calls `session.commit()` after every single chunk, generating N fsync calls per document. Additionally opens 3 separate DB sessions sequentially where 1 would suffice.
- **File uploads** (`documents.py`, `api_docs/routes.py`): Use blocking `open()`/`write()` in async endpoints, stalling the event loop.
- **Cache-hit paths** (`query/routes.py`): Fetch source chunks one-at-a-time in a loop (N+1 pattern, 6 occurrences).
- **CustomEnsembleRetriever** (`retrieval_langchain.py`): Silently returns `[]` when `_get_relevant_documents()` is called from a running event loop instead of raising an error.
- **Response verification** (`verification.py`): Scores each sentence individually via cross-encoder rather than batching all sentence-source pairs.
- **Parser imports** (`parsers/base.py`): 6 redundant `import asyncio` inside method bodies despite top-level import.

## Goals / Non-Goals

**Goals:**
1. Eliminate cross-event-loop state in the DSPy pipeline (critical bug fix)
2. Reduce SQLite fsync pressure by batching per-chunk commits
3. Prevent event-loop blocking by offloading sync file I/O to aiofiles
4. Eliminate N+1 queries in all cache-hit paths
5. Replace silent failure with explicit error in `CustomEnsembleRetriever`
6. Improve cross-encoder throughput by batching predictions
7. Reduce redundant DB session churn in the processing loop
8. Clean up duplicate imports

**Non-Goals:**
- No new capabilities or features
- No changes to the RAG query schema, API contract, or public interfaces
- No changes to DSPy internals or the LLM/embedder singleton lifecycle
- No introduction of external message queues or task persistence
- No changes to the frontend or client code

## Decisions

### D-1: DSPy event-loop bridge → `run_coroutine_threadsafe`

| Decision | Apply to |
|----------|----------|
| Replace `asyncio.run()` with `asyncio.get_running_loop()` detection + `asyncio.run_coroutine_threadsafe()` for sync-to-async bridging | `module.py:183`, `lm_adapter.py:173` |

**Rationale:** `asyncio.run()` can only be called when no event loop is running in the current thread. In the current code:
- `manager.py` calls `module.forward()` via `asyncio.to_thread()` (new thread with no running loop)
- `asyncio.run()` inside `module.forward()` creates a new event loop on that thread
- This new loop is different from the main event loop, so any async singleton created on the main loop emits `RuntimeError` if touched

We remove the `asyncio.to_thread()` call in `manager.py` and call `module.forward()` directly on the main thread (it's synchronous). For the sync-to-async bridge, we use `asyncio.get_running_loop()` to detect we're on the main event loop, then schedule the coroutine via `asyncio.run_coroutine_threadsafe(coro, loop)` which returns a `concurrent.futures.Future`. Calling `.result()` on that future blocks synchronously until the coroutine completes on the running loop.

```python
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    # No running loop (e.g., fresh thread) — use asyncio.run()
    results = asyncio.run(self.hybrid_retriever.retrieve(query, top_k=top_k))
else:
    # Running loop exists — schedule coroutine and block
    future = asyncio.run_coroutine_threadsafe(
        self.hybrid_retriever.retrieve(query, top_k=top_k), loop
    )
    results = future.result()
```

**Alternatives considered:**
- `nest_asyncio` (monkey-patch): Fragile, masks legitimate bugs, and discouraged by Python core devs.
- Making `APIDocRAG.forward()` fully async: Requires DSPy predictor changes since dspy.ChainOfThought calls `lm.forward()` synchronously internally. Too invasive.
- `loop.run_until_complete()`: Fails with `RuntimeError` when loop is already running.

### D-2: Manager removes `asyncio.to_thread()`

| Decision | Apply to |
|----------|----------|
| Replace `await asyncio.to_thread(module.forward, ...)` with direct synchronous call `module.forward(...)` | `manager.py:554` |

**Rationale:** Once `module.forward()` correctly handles the running-loop case (D-1), there's no need for the thread boundary. `module.forward()` is a synchronous method that does I/O-wait via `run_coroutine_threadsafe` (which blocks the calling thread) — putting it in a thread just adds overhead. DSPy module internals also work synchronously, so no issue.

### D-3: Batch SQLite commits at 10-chunk intervals

| Decision | Apply to |
|----------|----------|
| Reduce per-chunk `session.commit()` to `session.flush()`, commit every 10 chunks | `processor.py:402,566` |

**Rationale:** Each SQLite commit triggers an fsync. For a 500-chunk document, that's 500 fsync calls. The existing progress-update code already commits at 10-chunk intervals (line 568: `if i % 10 == 0`). We align the commit batching with this same interval. The stale-task detection at line 576 reads committed data — since we now only commit every 10 chunks, the stale check also moves to the batch boundary.

```python
await session.flush()  # Instead of commit() at line 402
# ...
if i % 10 == 0 or i == chunk_count - 1:
    await session.commit()  # Full commit at batch boundaries
    # stale-task detection uses this committed state
```

### D-4: Offload file writes to `aiofiles`

| Decision | Apply to |
|----------|----------|
| Replace `open()`/`write()` with `aiofiles.open()` | `documents.py:247`, `api_docs/routes.py:332` |

**Rationale:** `open()` + `f.write()` blocks the event loop for the duration of the I/O. For files up to 50MB, this can cause noticeable latency. `aiofiles` provides file I/O in a thread pool, keeping the event loop responsive. Add `aiofiles` to `pyproject.toml` dependencies.

### D-5: Batch N+1 chunk queries to single `IN` query

| Decision | Apply to |
|----------|----------|
| Replace per-chunk SELECT loop with single `select(Chunk).where(Chunk.id.in_(...))` | `query/routes.py:80-88` (and 5 other locations) |

**Rationale:** The classic N+1 problem. For 5 source chunks, 5 separate SQL queries vs. 1. The `id.in_()` pattern is standard SQLAlchemy and produces a single `WHERE id IN (?, ?, ...)` query. All 6 cache-hit paths across the file follow the same pattern and get the same fix.

### D-6: Raise explicit error instead of silent empty return

| Decision | Apply to |
|----------|----------|
| Replace `return []` with `raise RuntimeError(...)` | `retrieval_langchain.py:241` |

**Rationale:** Returning an empty list silently when `_get_relevant_documents()` is called from an async context hides bugs. The proper usage is the async `_aget_relevant_documents()` method. Raising a clear error makes misuse visible immediately.

### D-7: Batch cross-encoder scoring

| Decision | Apply to |
|----------|----------|
| Collect all (sentence, source) pairs into a single `model.predict()` call | `verification.py:156-174` |

**Rationale:** Currently `_score_with_cross_encoder()` is called once per sentence, each calling `model.predict()` with `len(source_texts)` pairs. For 10 sentences × 10 sources, that's 10 separate `predict()` calls. Batching into one call improves throughput because `model.predict()` has fixed per-call overhead.

```python
# Before: per-sentence predict
for sentence in sentences:
    cross_scores = await self._score_with_cross_encoder(sentence, source_texts)

# After: single batch predict
all_pairs = [(s, src) for s in sentences for src in source_texts]
all_scores = await self._score_all_cross_encoder(all_pairs, len(source_texts))
```

### D-8: Consolidate redundant DB sessions

| Decision | Apply to |
|----------|----------|
| Merge `session2` (line 162) into main session (line 120); keep `session_final` (line 590) as is | `processor.py:120-170, 590-601` |

**Rationale:** The main `session` (line 120) already holds a reference to the `Document` — there's no need for a second session to update `total_chars`. Move the `total_chars` update into the main session before the chunk processing loop. Keep the final completion session separate only if needed for transaction isolation (it already has the document loaded, so actually it can also be consolidated — but the chunk-commit loop may have left the session in a state where a fresh session is clearer).

**Alternative:** Consolidate all three sessions (main + session2 + session_final) into the main session. Since per-chunk commits are removed (D-3), the main session stays clean through the loop.

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| **D-1**: `run_coroutine_threadsafe` blocks the calling thread. If the event loop is busy, the calling thread blocks until the coroutine completes. In the LM adapter, this could delay DSPy predictor execution. | The MLX model runs synchronously in a thread pool (`asyncio.to_thread`). The `run_coroutine_threadsafe` path is only used for the async wrapper that calls the LLM. Latency is bounded by model inference time (seconds, not minutes). |
| **D-3**: Batch-committing 10 chunks means losing up to 10 chunks on crash instead of 1. | Acceptable trade-off. The persisted data is auto-generated chunks re-creatable from the source document. A full reprocess is always available. |
| **D-5**: If `source_chunk_ids` is large (100+), a single `IN` query may be slower than batched `IN` queries. | Current usage shows 5-10 source chunks per cache hit. Even at 100, SQLite handles `IN` efficiently. Not a concern. |
| **D-7**: Single-batch `predict()` for all pairs means if one pair fails, the whole batch fails. | The cross-encoder model is deterministic (not an LLM with variable output). Failures would indicate OOM, not individual pair issues. If OOM is a concern, fall back to chunked batching. |
| **D-8**: Consolidating sessions reduces isolation between chunk writes and document metadata updates. | Session isolation is not critical here — the document row is only read by the stale-task detection and the user-facing status endpoint. Both can tolerate slightly stale reads. |

## Migration Plan

No deployment/migration needed — all changes are in-place code modifications with no schema changes. Each fix is independently testable:

1. DSPy fixes verified by existing integration tests for `api-docs-rag` pipeline
2. Commit batching verified by existing processing integration tests
3. aiofiles verified by upload-document integration tests
4. N+1 fix verified by query-cache integration tests
5. Cross-encoder batching verified by verification unit/integration tests
6. All changes covered by `uv run pytest` test suite run

Rollback: Each file change is self-contained. Revert the specific file to undo.

## Open Questions

1. **aiofiles version pin**: What minimum `aiofiles` version to add to `pyproject.toml`? (Likely `>=23.0.0` based on current Python 3.11+ constraint.)
2. **DSPy test coverage**: Are there existing integration tests that exercise the DSPy pipeline end-to-end (manager.query_dspy → module.forward → lm_adapter.forward)? The audit found the `api-docs-rag` capability is modified — verify test coverage exists.
