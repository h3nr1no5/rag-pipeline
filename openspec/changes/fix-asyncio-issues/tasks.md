## 1. DSPy Event-Loop Lifecycle Fix

- [ ] 1.1 Fix `module.py` — Replace `asyncio.run()` with running-loop detection + `asyncio.run_coroutine_threadsafe()` in `_forward_impl()`, preserving `asyncio.run()` fallback for thread contexts
- [ ] 1.2 Fix `manager.py` — Remove `asyncio.to_thread()` wrapper in `_query_dspy()`, call `module.forward()` directly
- [ ] 1.3 Fix `lm_adapter.py` — Replace `asyncio.run()` with running-loop detection + `asyncio.run_coroutine_threadsafe()` in `MLXDspyLM.forward()`
- [ ] 1.4 Run DSPy pipeline integration tests to verify no regression

## 2. Batch SQLite Commits in Processing Loop

- [ ] 2.1 Replace per-chunk `session.commit()` with `session.flush()` in `process_document_async()` chunk-saving loop (line 402)
- [ ] 2.2 Add `session.commit()` at 10-chunk batch boundaries aligned with existing progress reporting (line 568)
- [ ] 2.3 Move stale-task detection (`session.get(Document, ...)`) to run after each batch commit
- [ ] 2.4 Run document processing integration tests to verify correctness

## 3. Consolidate Redundant DB Sessions

- [ ] 3.1 Merge the second `async_session_maker()` session (line 162) into the main session for `total_chars` update
- [ ] 3.2 Merge the final completion `async_session_maker()` session (line 590) into the main session for `status = "completed"` update
- [ ] 3.3 Verify no regression in processing lifecycle integration tests

## 4. Offload Sync File I/O to aiofiles

- [ ] 4.1 Add `aiofiles` dependency to `pyproject.toml` (version constraint `>=23.0.0`)
- [ ] 4.2 Replace `open()`/`f.write()` in `src/api/routes/documents.py:247` with `aiofiles.open()`
- [ ] 4.3 Replace `open()`/`f.write()` in `src/domain/rag/api_docs/routes.py:332` with `aiofiles.open()`
- [ ] 4.4 Run `uv sync` to install new dependency
- [ ] 4.5 Verify upload integration tests pass

## 5. Fix N+1 Chunk Queries in Cache-Hit Paths

- [ ] 5.1 Replace per-chunk SELECT loop in `query/routes.py` (line 80-88) with single `select(Chunk).where(Chunk.id.in_(cached.source_chunk_ids))`
- [ ] 5.2 Apply same fix to all 5 other cache-hit locations in `query/routes.py` (lines 244, 439, 648, 856, 1002)
- [ ] 5.3 Run query-cache integration tests to verify correctness

## 6. Fix Silent Empty-Return in CustomEnsembleRetriever

- [ ] 6.1 Replace `return []` with `raise RuntimeError(...)` in `_get_relevant_documents()` when called from running event loop (line 241)
- [ ] 6.2 Ensure non-running-loop and no-loop cases also propagate exceptions instead of silent `return []`
- [ ] 6.3 Run LangChain retrieval integration tests to verify no regression

## 7. Batch Cross-Encoder Scoring in Verification

- [ ] 7.1 Add `_score_all_cross_encoder()` method to `ResponseVerifier` that accepts all (sentence, source) pairs in a single `model.predict()` call
- [ ] 7.2 Refactor `verify()` to collect all pairs upfront and call `_score_all_cross_encoder()` once
- [ ] 7.3 Split batch results back per-sentence for existing citation matching logic
- [ ] 7.4 Run verification integration tests to verify correctness

## 8. Clean Up Redundant Imports

- [ ] 8.1 Remove 6 redundant `import asyncio` from method bodies in `src/infrastructure/parsers/base.py` (lines 41, 59, 118, 134, 171, 174)
- [ ] 8.2 Verify parser unit tests still pass
