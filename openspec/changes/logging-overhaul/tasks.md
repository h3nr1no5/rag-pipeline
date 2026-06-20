## 1. Foundation — Core Logging Module

- [ ] 1.1 Create `src/core/logging.py` with `LogLevelManager` singleton class (in-memory `dict[str, int]` overrides, `get_level()`, `set_level()`, `reset()` methods)
- [ ] 1.2 Implement `log_structured(module_name, event_type, level=INFO, **context)` helper function that emits a single log line with `event_type key=value ...` format using the module's standard logger

## 2. DevModeFilter — Static Noise Suppression

- [ ] 2.1 Implement `DevModeFilter(logging.Filter)` class in `src/core/logging.py` that suppresses `uvicorn.access` INFO messages unless overridden to DEBUG
- [ ] 2.2 Register `DevModeFilter` on the root logger in `src/api/main.py` during app startup (or in `src/core/config.py` logging config)

## 3. Toggle Endpoint — Runtime Log Level Control

- [ ] 3.1 Create `src/api/routes/debug/__init__.py` and `src/api/routes/debug/routes.py` with `GET /api/v1/debug/logging` returning current overrides as JSON
- [ ] 3.2 Implement `PUT /api/v1/debug/logging` accepting `{module: level | null}` to set/clear overrides, delegating to `LogLevelManager`
- [ ] 3.3 Wire up the debug router in `src/api/main.py` under `/api/v1/debug` prefix, add auth dependency via `get_current_user` to all routes
- [ ] 3.4 Create a `ModuleLevelFilter(logging.Filter)` that consults `LogLevelManager.get_level()` for each log record and overrides its effective level, register on root logger

## 4. Middleware Cleanup

- [ ] 4.1 In `src/api/main.py`, remove the `logger.info("Request started | ID: ...")` line from `MonitoringMiddleware.dispatch` — uvicorn access log covers request entry
- [ ] 4.2 Demote the `logger.info("Request completed | ID: ... | status: ...")` line to `logger.debug` — preserves observability for debugging without per-request noise at INFO

## 5. Embedder Logging Demotion

- [ ] 5.1 In `src/domain/services/embedding.py`, change `logger.info("Creating embedder instance...")` to `logger.debug`
- [ ] 5.2 In `src/domain/services/embedding.py`, consider consolidating the two-line init pattern (line 81 + line 84) into a single structured event

## 6. LLM Prompt Dump Replacement

- [ ] 6.1 In `src/domain/services/llm.py`, replace `logger.debug(f"Prompt ({len} chars): {formatted_prompt[:500]}...")` with `logger.debug(f"Prompt: hash={sha256(formatted_prompt)[:12]} len={len(formatted_prompt)}")` in both async `generate()` and sync `generate()` methods
- [ ] 6.2 Keep the existing `logger.debug("Applied chat template to prompt")` and `logger.debug(f"Starting generation (max_tokens=...)")` — these are low-volume and useful

## 7. Retriever Logging Collapse

- [ ] 7.1 In `src/api/routes/query/_retrieval.py`, replace the 9 sequential `logger.info()` calls in the retrieval function (lines 119, 155, 159, 161, 181, 198, 209, 225, 252) with a single `log_structured("retrieval", "query", user_id=..., document_count=..., chunk_count=..., top_k=..., latency_ms=...)` call at the function exit point
- [ ] 7.2 Keep the `logger.error()` and `logger.warning()` calls — these are exceptional paths, not stage gates
- [ ] 7.3 Update `logger.info(f"Top {len(top_chunks)} chunks with scores: ...")` to include scores summary in the structured event rather than a separate line

## 8. Init Log Consolidation

- [ ] 8.1 In `src/domain/services/retrieval_langchain.py`, replace the multi-line init sequence (BM25 building, FAISS building, hybrid init) with a single `log_structured("retrieval", "init", bm25_built=True, faiss_built=True, elapsed_ms=...)` line
- [ ] 8.2 In `src/domain/services/embedding.py`, replace the load sequence logs with a single structured event
- [ ] 8.3 In `src/domain/services/llm.py`, consolidate LLM loading logs (model_path, load_time) into a single structured event
- [ ] 8.4 In `src/domain/services/chain_langchain.py`, replace the 2 sequential `logger.info()` calls in `initialize()` (lines 143, 163) with a single `log_structured("chain_langchain", "init", ...)` event

## 9. Processor Deduplication

- [ ] 9.1 In `src/domain/services/processor.py`, identify and merge duplicated log branches (the semantic and non-semantic processing paths share similar logging patterns around embedder loading and chunk embedding)
- [ ] 9.2 Replace `logger.info("Embedder loaded for document processing")` in both branches with a single structured event at the shared call point

## 10. Tests

- [ ] 10.1 Write unit tests for `LogLevelManager` (set, get, reset, default behavior)
- [ ] 10.2 Write unit tests for `DevModeFilter` (suppresses uvicorn.access INFO, passes ERROR, passes DEBUG when overridden)
- [ ] 10.3 Write unit tests for `log_structured()` helper (correct format, uses correct logger)
- [ ] 10.4 Write integration tests for toggle endpoint (GET returns levels, PUT sets level, 401 without auth, 422 for invalid input)
- [ ] 10.5 Write integration test verifying `_retrieval.py` produces 1 log line instead of 7 per query
- [ ] 10.6 Write integration test verifying prompt dump is not emitted at DEBUG (hash+len is emitted instead)
- [ ] 10.7 Verify existing tests still pass: `uv run pytest tests/`
