## 1. WarmupState — Refactor to dict-based registry

- [ ] 1.1 Replace `cross_encoder`/`llm` dataclass fields with `dict[str, ModelStatus]` registry
- [ ] 1.2 Add generic `update(model_name, **kwargs)` method using `asyncio.Lock`
- [ ] 1.3 Add generic `get_status(model_name) -> ModelStatus` method
- [ ] 1.4 Rewrite `to_dict()` to iterate over all models in registry
- [ ] 1.5 Update `all_ready` and `any_loading` properties to check dict values
- [ ] 1.6 Add `message` field to `ModelStatus` dataclass
- [ ] 1.7 Rename update methods from `update_cross_encoder`/`update_llm` to generic `update()` — update all callers
- [ ] 1.8 Update `get_warmup_state()` tests to work with new dict-based API

## 2. WarmupState — Add embedder + dspy_lm tracking

- [ ] 2.1 Add `"embedder"` and `"dspy_lm"` entries to the WarmupState registry on initialization
- [ ] 2.2 Map existing `_embedder_instance` check to populate initial status
- [ ] 2.3 Add import for `get_mlx_dspy_lm` in warmup code path

## 3. Embedder — Async warmup in warmup_models()

- [ ] 3.1 Extract `SentenceTransformerEmbedder` loading into a sync helper function
- [ ] 3.2 Add `_load_embedder()` async function in `warmup_models()` that calls `asyncio.to_thread()`
- [ ] 3.3 Set `_embedder_instance` global after successful thread-pool load
- [ ] 3.4 Update progress in WarmupState during load (0→100)
- [ ] 3.5 Log load time and model info after successful load
- [ ] 3.6 Handle errors: set status to "error" with exception message
- [ ] 3.7 Update `get_embedder()` to prefer already-loaded instance; still keep lazy fallback

## 4. DSPy LM — Instant warmup after LLM

- [ ] 4.1 In `warmup_models()`, after LLM status becomes "ready": call `get_mlx_dspy_lm()` if `api_docs_enabled`
- [ ] 4.2 Set WarmupState `"dspy_lm"` to ready with progress=100 immediately after instantiation
- [ ] 4.3 Move DSPy `dspy.configure(lm=...)` to happen during warmup (currently in lifespan after warmup launch)

## 5. Granular progress — HF Hub download callbacks

- [ ] 5.1 Identify all `snapshot_download()` calls in the codebase (LLM, cross-encoder, embedder)
- [ ] 5.2 Create `_make_progress_callback(model_name, state)` factory function
- [ ] 5.3 Pass callback to `snapshot_download()` for each model download
- [ ] 5.4 Handle callback from thread: use `asyncio.run_coroutine_threadsafe()` with stored event loop reference
- [ ] 5.5 Store `asyncio.get_event_loop()` reference in WarmupState or a module global
- [ ] 5.6 Add `message` updates during download phases ("Downloading...", "Loading into memory...")

## 6. Auto-retry — Exponential backoff on error

- [ ] 6.1 Create `_retry_with_backoff(model_name, state, load_fn, retry_count)` async helper
- [ ] 6.2 Implement backoff: delay = min(30, 2 * 2^retry_count)
- [ ] 6.3 Reset status to "loading" and progress to 0 on each retry
- [ ] 6.4 Escalate to "permanent_error" after 5 consecutive retries at 30s cap
- [ ] 6.5 Schedule retry via `asyncio.create_task()` from error handler in warmup_models()
- [ ] 6.6 Reset retry count on successful retry
- [ ] 6.7 Ensure retry works for all 3 model types that do actual loading (llm, cross_encoder, embedder)

## 7. Model readiness gate — require_models dependency

- [ ] 7.1 Create `require_models(*model_names)` async callable in `src/api/dependencies.py` or new `src/api/gate.py`
- [ ] 7.2 Implement check: iterate model_names, query WarmupState, raise `HTTPException(503)` with `Retry-After` header
- [ ] 7.3 Return different messages for "loading" vs "error" vs "permanent_error" states
- [ ] 7.4 Apply `Depends(require_models("llm"))` to `POST /query` and `/query/stream`
- [ ] 7.5 Apply `Depends(require_models("llm", "cross_encoder"))` to `POST /query/langchain` and `/langchain/stream`
- [ ] 7.6 Apply `Depends(require_models("llm"))` to `POST /query/llamaindex` and `/llamaindex/stream`
- [ ] 7.7 Apply `Depends(require_models("llm", "dspy_lm"))` to API docs query routes
- [ ] 7.8 Apply `Depends(require_models("embedder"))` to `POST /documents`
- [ ] 7.9 For streaming endpoints: add gate check at top of event generators (since Depends doesn't apply to generator internals)

## 8. Remove ad-hoc cross-encoder checks

- [ ] 8.1 Remove inline `warmup_state.cross_encoder.status == "error"` check from LangChain POST handler
- [ ] 8.2 Remove inline `warmup_state.cross_encoder.status == "error"` check from LangChain stream handler
- [ ] 8.3 Verify no other ad-hoc readiness checks remain

## 9. Update /health/models endpoint

- [ ] 9.1 Add embedder and dspy_lm to the response (WarmupState.to_dict() now handles this)
- [ ] 9.2 Update sanitization to include all 4 models
- [ ] 9.3 Add `message` field to the response schema for each model

## 10. Frontend — Gateway screen

- [ ] 10.1 Replace simple progress bar list with per-model status cards
- [ ] 10.2 Remove the `models_poll_count > 60` timeout bypass
- [ ] 10.3 Add per-card rendering: model name, status icon (spinner/✅/⚠️/❌), progress bar, message
- [ ] 10.4 Update model key/display-name mapping for all 4 models
- [ ] 10.5 Handle "permanent_error" state with ❌ icon and guidance text
- [ ] 10.6 Handle "error" state with retry message ("Error — retrying in Xs...")
- [ ] 10.7 Use `st.empty()` placeholders to avoid layout shifts
- [ ] 10.8 Stop polling on "permanent_error" (not just on error)

## 11. Frontend — Disabled inputs with tooltips

- [ ] 11.1 Disable "🔵 Cosine Sim" and "🟢 LlamaIndex" checkboxes with tooltip when LLM not ready
- [ ] 11.2 Disable "🟣 LangChain" checkbox with tooltip when cross-encoder not ready
- [ ] 11.3 Disable "🔶 API Docs" checkbox with tooltip when DSPy LM not ready
- [ ] 11.4 Disable document upload button with tooltip when embedder not ready
- [ ] 11.5 Hide/disable chat input until all required models are ready
- [ ] 11.6 Remove the old `st.info()` "Some models failed — you can still use chat" message

## 12. Frontend — 503 error handling in queries

- [ ] 12.1 Update `query_sync()`, `query_langchain_sync()`, `query_llamaindex_sync()`, `api_docs_query()` to handle 503 responses
- [ ] 12.2 Display clear error message instead of spinner when backend returns 503
- [ ] 12.3 Show the backend's error detail in the UI (e.g., "Model 'llm' is still loading")

## 13. Testing

- [ ] 13.1 Unit tests for dict-based WarmupState (update, get_status, to_dict, all_ready, any_loading)
- [ ] 13.2 Unit tests for `require_models` gate function (all combinations of ready/loading/error)
- [ ] 13.3 Unit tests for auto-retry backoff calculation
- [ ] 13.4 Unit tests for progress callback factory
- [ ] 13.5 Integration tests for /health/models returning all 4 models
- [ ] 13.6 Integration tests for 503 on each gated route (mock WarmupState to loading/error)
- [ ] 13.7 Integration tests for streaming endpoints returning 503 via SSE
- [ ] 13.8 Integration test: embedder warmup sets global instance
- [ ] 13.9 Integration test: DSPy LM instant after LLM ready
- [ ] 13.10 Integration test: ad-hoc cross-encoder check removed (LangChain routes gate via unified check)
