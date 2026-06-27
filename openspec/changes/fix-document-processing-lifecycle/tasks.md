## 1. Remove redundant `format_graph()` call

- [ ] 1.1 Modify `ApiEmbeddingIndex.add_graph()` to check `any(not node.content for node in graph.nodes.values())` and skip `format_graph()` when content is already populated
- [ ] 1.2 Write unit test `tests/unit/test_embedding_index_format.py` covering both pre-formatted and empty-content paths (Scenario 4a and 4b)

## 2. Add progress callback hooks to embedding index

- [ ] 2.1 Add optional `progress_callback: Callable[[str, str], Awaitable[None]] | None = None` parameter to `ApiEmbeddingIndex.add_graph()`
- [ ] 2.2 Call `progress_callback("indexing", "Loading embedding model…")` before model load and `progress_callback("indexing", f"Embedding {N} chunks…")` before batch encoding
- [ ] 2.3 Wire the callback in `src/domain/services/processor.py`'s `_process_api_doc()` by passing a lambda that calls `update_document_progress()`
- [ ] 2.4 Write unit test `tests/unit/test_embedding_index_progress.py` verifying callback is invoked at the correct stages with expected messages

## 3. Extend model warmup to include embedding model

- [ ] 3.1 Add `get_embedder()` call (wrapped in try/except) to the `_load_models()` coroutine in `src/api/main.py`
- [ ] 3.2 Log the embedding dimension on successful warmup for observability

## 4. Add pending-document recovery on startup

- [ ] 4.1 Add recovery loop in `src/api/main.py` lifespan, after `load_all_from_db()`, querying `SELECT ... WHERE status="pending"`, gated behind `settings.api_docs_enabled`
- [ ] 4.2 Log `"Resumed N pending document(s) for processing"` when pending docs are found
- [ ] 4.3 Write unit test `tests/unit/test_startup_recovery.py` verifying pending docs are picked up, file-not-found docs fail gracefully, and zero pending docs does nothing

## 5. Verification

- [ ] 5.1 Run `ruff check .` — fix any lint errors
- [ ] 5.2 Run `mypy src/` — fix any type errors
- [ ] 5.3 Run `uv run pytest tests/unit/ -v` — all unit tests pass
- [ ] 5.4 Run `uv run pytest tests/integration/test_processing_perf.py -v --timeout=120` — performance regression test passes
- [ ] 5.5 Run `uv run pytest tests/integration/ -v -k "not slow"` — integration tests pass
