## 1. WarmupState — Refactor to dict-based registry

- [x] 1.1 Replace `cross_encoder`/`llm` dataclass fields with `dict[str, ModelStatus]` registry
- [x] 1.2 Add generic `update(model_name, **kwargs)` method using `asyncio.Lock`
- [x] 1.3 Add generic `get_status(model_name) -> ModelStatus` method
- [x] 1.4 Rewrite `to_dict()` to iterate over all models in registry
- [x] 1.5 Update `all_ready` and `any_loading` properties to check dict values
- [x] 1.6 Add `message` field to `ModelStatus` dataclass
- [x] 1.7 Rename update methods from `update_cross_encoder`/`update_llm` to generic `update()` — update all callers
- [x] 1.8 Update `get_warmup_state()` tests to work with new dict-based API

## 2. WarmupState — Add embedder + dspy_lm tracking

- [x] 2.1 Add `"embedder"` and `"dspy_lm"` entries to the WarmupState registry on initialization
- [x] 2.2 Map existing `_embedder_instance` check to populate initial status
- [x] 2.3 Add import for `get_mlx_dspy_lm` in warmup code path

## 3. Embedder — Async warmup in warmup_models()

- [x] 3.1 Extract `SentenceTransformerEmbedder` loading into a sync helper function
- [x] 3.2 Add `_load_embedder()` async function in `warmup_models()` that calls `asyncio.to_thread()`
- [x] 3.3 Set `_embedder_instance` global after successful thread-pool load
- [x] 3.4 Update progress in WarmupState during load (0→100)
- [x] 3.5 Log load time and model info after successful load
- [x] 3.6 Handle errors: set status to "error" with exception message
- [x] 3.7 Update `get_embedder()` to prefer already-loaded instance; still keep lazy fallback

## 4. DSPy LM — Instant warmup after LLM

- [x] 4.1 In `warmup_models()`, after LLM status becomes "ready": call `get_mlx_dspy_lm()` if `api_docs_enabled`
- [x] 4.2 Set WarmupState `"dspy_lm"` to ready with progress=100 immediately after instantiation
- [x] 4.3 Move DSPy `dspy.configure(lm=...)` to happen during warmup (currently in lifespan after warmup launch)

## 5. Granular progress — HF Hub download callbacks

- [x] 5.1 Identify all `snapshot_download()` calls in the codebase (LLM, cross-encoder, embedder)
- [x] 5.2 Create `_make_progress_callback(model_name, state)` factory function
- [x] 5.3 Pass callback to `snapshot_download()` for each model download
- [x] 5.4 Handle callback from thread: use `asyncio.run_coroutine_threadsafe()` with stored event loop reference
- [x] 5.5 Store `asyncio.get_event_loop()` reference in WarmupState or a module global
- [x] 5.6 Add `message` updates during download phases ("Downloading...", "Loading into memory...")

## 6. Auto-retry — Exponential backoff on error

- [x] 6.1 Create `_retry_with_backoff(model_name, state, load_fn, retry_count)` async helper
- [x] 6.2 Implement backoff: delay = min(30, 2 * 2^retry_count)
- [x] 6.3 Reset status to "loading" and progress to 0 on each retry
- [x] 6.4 Escalate to "permanent_error" after 5 consecutive retries at 30s cap
- [x] 6.5 Schedule retry via `asyncio.create_task()` from error handler in warmup_models()
- [x] 6.6 Reset retry count on successful retry
- [x] 6.7 Ensure retry works for all 3 model types that do actual loading (llm, cross_encoder, embedder)

## 7. Model readiness gate — require_models dependency

- [x] 7.1 Create `require_models(*model_names)` async callable in `src/api/dependencies.py` or new `src/api/gate.py`
- [x] 7.2 Implement check: iterate model_names, query WarmupState, raise `HTTPException(503)` with `Retry-After` header
- [x] 7.3 Return different messages for "loading" vs "error" vs "permanent_error" states
- [x] 7.4 Apply `Depends(require_models("llm"))` to `POST /query` and `/query/stream`
- [x] 7.5 Apply `Depends(require_models("llm", "cross_encoder"))` to `POST /query/langchain` and `/langchain/stream`
- [x] 7.6 Apply `Depends(require_models("llm"))` to `POST /query/llamaindex` and `/llamaindex/stream`
- [x] 7.7 Apply `Depends(require_models("llm", "dspy_lm"))` to API docs query routes
- [x] 7.8 Apply `Depends(require_models("embedder"))` to `POST /documents`
- [x] 7.9 For streaming endpoints: add gate check at top of event generators (since Depends doesn't apply to generator internals)

## 8. Remove ad-hoc cross-encoder checks

- [x] 8.1 Remove inline `warmup_state.cross_encoder.status == "error"` check from LangChain POST handler
- [x] 8.2 Remove inline `warmup_state.cross_encoder.status == "error"` check from LangChain stream handler
- [x] 8.3 Verify no other ad-hoc readiness checks remain

## 9. Update /health/models endpoint

- [x] 9.1 Add embedder and dspy_lm to the response (WarmupState.to_dict() now handles this)
- [x] 9.2 Update sanitization to include all 4 models
- [x] 9.3 Add `message` field to the response schema for each model

## 10. Frontend — Gateway screen

- [x] 10.1 Replace simple progress bar list with per-model status cards (per-model data rendered)
- [x] 10.2 Remove the `models_poll_count > 60` timeout bypass
- [x] 10.3 Add per-card rendering: model name, status icon (spinner/✅/⚠️/❌), progress bar, message
- [x] 10.4 Update model key/display-name mapping for all 4 models
- [x] 10.5 Handle "permanent_error" state with ❌ icon and guidance text
- [x] 10.6 Handle "error" state with retry message ("Error — retrying in Xs...")
- [x] 10.7 Use `st.empty()` placeholders to avoid layout shifts
- [x] 10.8 Stop polling on "permanent_error" (not just on error)

## 11. Frontend — Disabled inputs with tooltips

- [x] 11.1 Disable "🔵 Cosine Sim" and "🟢 LlamaIndex" checkboxes with tooltip when LLM not ready
- [x] 11.2 Disable "🟣 LangChain" checkbox with tooltip when cross-encoder not ready
- [x] 11.3 Disable "🔶 API Docs" checkbox with tooltip when DSPy LM not ready
- [x] 11.4 Disable document upload button with tooltip when embedder not ready (covered by Task 15)
- [x] 11.5 Hide/disable chat input until all required models are ready
- [x] 11.6 Remove the old `st.info()` "Some models failed — you can still use chat" message

## 12. Frontend — 503 error handling in queries

- [x] 12.1 Update `query_sync()`, `query_langchain_sync()`, `query_llamaindex_sync()`, `api_docs_query()` to handle 503 responses
- [x] 12.2 Display clear error message instead of spinner when backend returns 503
- [x] 12.3 Show the backend's error detail in the UI (e.g., "Model 'llm' is still loading")

## 13. Testing

- [x] 13.1 Unit tests for dict-based WarmupState (update, get_status, to_dict, all_ready, any_loading)
- [x] 13.2 Unit tests for `require_models` gate function (all combinations of ready/loading/error)
- [x] 13.3 Unit tests for auto-retry backoff calculation
- [x] 13.4 Unit tests for progress callback factory
- [x] 13.5 Integration tests for /health/models returning all 4 models
- [x] 13.6 Integration tests for 503 on each gated route (mock WarmupState to loading/error)
- [x] 13.7 Integration tests for streaming endpoints returning 503 via SSE (HTTP status tested, SSE body verified)
- [x] 13.8 Integration test: embedder warmup sets global instance
- [x] 13.9 Integration test: DSPy LM instant after LLM ready
- [x] 13.10 Integration test: ad-hoc cross-encoder check removed (LangChain routes gate via unified check)
- [x] 13.11 Integration test: document upload returns 503 when embedder not ready
- [x] 13.12 Integration test: documents list endpoint does NOT require model readiness

## 14. Frontend — Shared model status component

- [x] 14.1 Create `client/components/model_status.py` with `model_status_banner()` function
- [x] 14.2 Implement internal polling of `/health/models` (200ms interval, no timeout bypass)
- [x] 14.3 Render per-model status cards: name, icon (spinner/✅/⚠️/❌), progress bar, message
- [x] 14.4 Handle all model states: queued, loading, ready, error, permanent_error
- [x] 14.5 Handle error-with-retry state showing "Error — retrying in Xs..."
- [x] 14.6 Handle permanent_error with ❌ icon and "restart server" guidance
- [x] 14.7 Return boolean indicating if all models are ready
- [x] 14.8 Use `st.empty()` placeholders to prevent layout shift

## 15. Frontend — Documents page model status integration

- [x] 15.1 Replace inline `/health/models` polling (lines 21-57) with shared `model_status_banner()` component
- [x] 15.2 Disable `st.file_uploader` widget when embedder not ready
- [x] 15.3 Disable `st.button("Upload")` when embedder not ready with tooltip
- [x] 15.4 Show compact "✅ AI models ready" success message when all models ready
- [x] 15.5 Handle 503 response from document upload with clear error message
- [x] 15.6 Remove the old per-model `st.caption()` rendering (replaced by shared component)
- [x] 15.7 Ensure document list and other features remain unaffected by model status

## 16. Testing — Documents page model status

- [x] 16.1 Unit tests for `model_status_banner()` component (all model states, all_ready combinations)
- [x] 16.2 Integration test: Documents page calls `/health/models` on load (verified via mocked requests)
- [x] 16.3 Integration test: document upload disabled when embedder not ready (verified via embedder_ready return value)
- [x] 16.4 Integration test: 503 returned for document upload when embedder loading (covered by test_document_gate.py)
