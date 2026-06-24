## Context

The RAG pipeline loads 4 models at startup: LLM (MLX), cross-encoder reranker, sentence-transformers embedder, and DSPy LM adapter. Currently:

- **WarmupState** (`src/domain/services/warmup.py`) tracks only `llm` and `cross_encoder` — 2 `ModelStatus` dataclass fields with per-field update methods. Embedder and DSPy LM are untracked.
- **Embedder** loads **synchronously** on first call to `get_embedder()` — this happens during document upload processing (processor.py, retrieval.py, embedding_index.py), blocking that async task for 1-30s depending on model size.
- **DSPy LM** (`MLXDspyLM` in `lm_adapter.py`) wraps the same MLX LLM — it's instant after LLM is ready but currently loaded in `lifespan` without progress tracking.
- **Progress** is coarse: jumps 0→50→100. No download percentage visibility.
- **No error recovery**: if a model fails to load, it stays in `error` permanently.
- **Route gating** is ad-hoc: only `/langchain` endpoints check `cross_encoder.status == "error"`. All other endpoints call `get_llm()`/`get_embedder()` directly, which blocks if the model is still loading.
- **Frontend** polls `/health/models` at 0.2s intervals with a 60-poll (~12s) timeout that **forces `models_ready=True`** regardless of actual status.

## Goals / Non-Goals

**Goals:**
- Unify all 4 models under a single `WarmupState` with consistent status/progress/error tracking
- Make embedder load async via `asyncio.to_thread()` during `warmup_models()`
- DSPy LM warms up instantly after LLM (same MLX model) with status tracking
- Granular 0-100 download progress via HF Hub `snapshot_download` callbacks
- Auto-retry with exponential backoff (2→4→8→16→30s cap, no max) for any model that errors
- Smart per-route gating: each route checks only models it needs, returns `503` + `Retry-After` header when not ready
- `permanent_error` status after backoff repeatedly hits 30s cap (to distinguish transient vs. fatal)
- Frontend gateway screen with per-model cards, disabled inputs with tooltips, no timeout bypass

**Non-Goals:**
- Not changing the model loading implementation itself (mlx-lm loading code, sentence-transformers init)
- Not adding new model types beyond the existing 4
- Not changing the DSPy LM's relationship to the LLM (it wraps the same singleton)
- Not changing how models are used at inference time — only warmup + gating
- Not adding Docker, CI/CD, or deployment changes
- Not removing the old progress model (0→50→100) — just replacing it with granular callbacks

## Decisions

### Decision 1: Unified WarmupState with dict-based model registry
**Choice**: Replace individual `cross_encoder`/`llm` dataclass attributes with a `dict[str, ModelStatus]` registry keyed by model name.

**Rationale**: Current WarmupState has 2 dedicated fields with per-field update methods (`update_cross_encoder`, `update_llm`). Adding 2 more models would quadruplicate these methods. A dict-based approach allows:
- Generic `update(model_name, **kwargs)` method
- Generic `get_status(model_name) -> ModelStatus`
- Generic iteration for `/health/models` serialization
- Easy future extension (just add a key)
- Same thread-safety (single `asyncio.Lock` covers the whole dict)

**Alternatives considered**: Keep per-field approach — rejected because it doesn't scale to 4+ models and requires code changes for every new model.

### Decision 2: Granular progress via optional download callback
**Choice**: Pass a `progress_callback(current, total)` closure to `snapshot_download()` during model download phase. The callback updates WarmupState. After download, set progress to 100 before model load begins.

**Rationale**: HF Hub's `snapshot_download()` accepts an optional `callback` parameter with signature `(downloads_started, downloads_total)`. Wrapping this gives real download percentage (0-99%) without any polling or estimation. The jump to 100 on load start is a minor visual artifact but far better than the current 0→50→100.

**Implementation plan**:
```python
def _make_progress_callback(model_name: str, state: WarmupState):
    def cb(downloads_started: int, downloads_total: int):
        if downloads_total > 0:
            pct = int(downloads_started / downloads_total * 99)  # 0-99
            asyncio.run_coroutine_threadsafe(
                state.update(model_name, progress=pct),
                loop,
            )
    return cb
```

**Risk**: `snapshot_download` callback may not fire for cached models — progress will jump from 0 to 100. Acceptable (model is cached so load is near-instant).

### Decision 3: Smart per-route gating via `require_models` dependency
**Choice**: Create a FastAPI `Depends` callable `require_models(*model_names: str)` that checks WarmupState and raises `HTTPException(503)` with `Retry-After` header if any model is not ready.

**Implementation**:
```python
async def require_models(*model_names: str) -> None:
    state = get_warmup_state()
    for name in model_names:
        ms = state.get_status(name)
        if ms.status in ("loading", "queued"):
            raise HTTPException(
                status_code=503,
                detail=f"Model '{name}' is still loading (progress: {ms.progress}%). Try again shortly.",
                headers={"Retry-After": "5"},
            )
        if ms.status in ("error", "permanent_error"):
            raise HTTPException(
                status_code=503,
                detail=f"Model '{name}' failed to load and is being retried.",
                headers={"Retry-After": "10"},
            )
```

Then applied as route dependencies:
```python
@router.post("", dependencies=[Depends(require_models("llm"))])
async def query_documents(...): ...

@router.post("/langchain", dependencies=[Depends(require_models("llm", "cross_encoder"))])
async def query_documents_langchain(...): ...

@router.post("/documents", dependencies=[Depends(require_models("embedder"))])
async def upload_document(...): ...
```

**Rationale**: FastAPI `Depends` in `dependencies=[...]` is the idiomatic way to apply pre-route checks. It keeps the guard logic separate from route logic, is easily testable, and scales to any combination of models.

**Model dependency map**:
| Route(s) | Models Required |
|----------|----------------|
| `POST /query` + `/query/stream` | `llm` |
| `POST /query/langchain` + `/langchain/stream` | `llm`, `cross_encoder` |
| `POST /query/llamaindex` + `/llamaindex/stream` | `llm` |
| `POST /query/api-docs/*` | `llm`, `dspy_lm` |
| `POST /documents` | `embedder` |
| `GET /health*`, `/auth/*`, `/docs`, `/strategies/*` | *(none)* |

### Decision 4: Auto-retry with exponential backoff
**Choice**: When a model transitions to `error`, schedule a retry with exponential backoff: 2s, 4s, 8s, 16s, 30s (capped), repeating indefinitely until success or `permanent_error` escalation.

**When does it become `permanent_error`?** After the model has consistently hit the 30s cap 5+ consecutive times (i.e., ~150+ seconds of total retry time). At this point, the frontend shows a "permanent failure — contact support" message rather than "retrying..."

**Implementation**: A `_retry_with_backoff(model_name, retry_count)` coroutine scheduled via `asyncio.create_task` from within `warmup_models()` error handler. Each retry reloads the model. Success resets the retry count.

```python
async def _retry_with_backoff(model_name: str, state: WarmupState, load_fn, retry_count: int = 0):
    delay = min(30, 2 * 2 ** retry_count)  # 2, 4, 8, 16, 30, 30, ...
    await asyncio.sleep(delay)
    try:
        await state.update(model_name, status="loading", progress=0, error=None)
        await load_fn()
        await state.update(model_name, status="ready", progress=100)
    except Exception as e:
        new_count = retry_count + 1
        if delay >= 30 and retry_count >= 5:
            await state.update(model_name, status="permanent_error", error=str(e))
        else:
            await state.update(model_name, status="error", error=str(e))
            asyncio.create_task(_retry_with_backoff(model_name, state, load_fn, new_count))
```

**Rationale**: Exponential backoff prevents hammering Hugging Face Hub or the local filesystem during transient failures (network blips, OOM). The 30s cap ensures retry frequency stays reasonable. The `permanent_error` escalation prevents infinite retries in genuinely broken configurations.

### Decision 5: Frontend gateway — disable, don't bypass
**Choice**: Replace the current polling time-out bypass (`if poll_count > 60: models_ready = True`) with a persistent gateway that never auto-proceeds. The user sees model status cards and must wait. If a model enters `permanent_error`, show a message asking them to reload or contact support.

**Implementation**:
- Same polling loop (200ms) but no max-poll cutoff
- Per-model cards instead of a single progress list
- Cards show: model name, progress bar, status message ("Downloading...", "Loading into memory...", "Ready ✅", "Error — retrying in Xs...", "Permanent failure — restart server")
- RAG method checkboxes disabled with tooltips when their required model isn't ready
- Upload button disabled with tooltip when embedder not ready
- Once all models are ready or `permanent_error`, polling stops

**Rationale**: The timeout bypass creates a race where users can submit queries before models are ready, causing either 503 errors or blocking behavior. Disallowing it completely is simpler and more honest.

### Decision 6: Embedder async loading via `asyncio.to_thread`
**Choice**: Load the sentence-transformers embedder inside `warmup_models()` using `asyncio.to_thread()`, similar to how LLM and cross-encoder are already loaded.

**Implementation**:
```python
async def _load_embedder(state: WarmupState):
    await state.update("embedder", status="loading", progress=0,
                       model=settings.embedding_model)
    try:
        from ..services.embedding import SentenceTransformerEmbedder, _embedder_instance
        def _load():
            global _embedder_instance
            _embedder_instance = SentenceTransformerEmbedder()
            return _embedder_instance
        await asyncio.wait_for(asyncio.to_thread(_load), timeout=120)
        await state.update("embedder", status="ready", progress=100)
    except Exception as e:
        raise
```

The existing `get_embedder()` function's lazy-init path becomes a fallback only (for the unlikely case the model isn't loaded during warmup, e.g., if the warmup task was cancelled).

### Decision 7: DSPy LM warmup is instant
**Choice**: DSPy LM wraps the same MLX LLM singleton — when the LLM is ready, the DSPy LM is effectively ready too. Warmup instantiates `MLXDspyLM()` after LLM is ready and immediately marks it `ready`.

**Implementation**: In `warmup_models()`, after LLM is ready:
```python
if settings.api_docs_enabled:
    from src.domain.rag.api_docs.pipeline.lm_adapter import get_mlx_dspy_lm
    get_mlx_dspy_lm()
    await state.update("dspy_lm", status="ready", progress=100)
```

**Rationale**: The constructor creates a lightweight wrapper (`MLXDspyLM.__init__` just stores config and references the existing `_llm_instance`). No actual model loading occurs.

### Decision 8: Shared model status component for Documents page

**Choice**: Create a reusable Streamlit component `model_status_banner()` in `client/components/` that both the Chat page and Documents page import to display model readiness status. The Documents page replaces its inline `/health/models` polling (lines 21-57) with this shared component.

**Rationale**: The Documents page already has a basic model check (lines 21-57 of `4_📁_Documents.py`) that calls `/health/models` and shows LLM + embedder status captions. However, it:
- Only shows 2 of 4 models (missing cross_encoder and dspy_lm)
- Doesn't handle the new `permanent_error` or `error-with-retry` states
- Doesn't disable the upload button when embedder isn't ready
- Will diverge from the Chat page's gateway UI

A shared component ensures consistency, reduces duplication, and handles all model states uniformly.

**Implementation**:
```python
# client/components/model_status.py
def model_status_banner(models_data: dict) -> bool:
    """
    Display model status banner and return True if all required models are ready.
    Shows per-model status, disables upload button if embedder not ready.
    """
    # Poll /health/models internally
    # Display status cards for all 4 models
    # Return ready/not-ready status
```

The Documents page call site becomes:
```python
from client.components.model_status import model_status_banner

models_data = get_health_models()
all_ready = model_status_banner(models_data)
if not all_ready:
    st.warning("Wait for models to be ready before uploading")
    # upload button and file uploader remain disabled
```

**Alternatives considered**: 
- Keep inline check — rejected because it duplicates logic and misses new model states
- Merge Documents page into the Chat page gateway — rejected because they serve different purposes; Documents needs to show models AND interact with document list simultaneously

### Decision 9: Document upload guarded by embedder readiness

**Choice**: The upload button (`st.button("Upload")`) in the Documents page sidebar SHALL be disabled when the embedder model is not in `ready` status. A tooltip SHALL explain why ("Embedder model is loading — please wait").

**Rationale**: The `POST /documents` endpoint already has `require_models("embedder")` applied (from Decision 3). If the embedder is not ready, the backend will return 503. Disabling the upload button proactively prevents users from attempting uploads that will fail, creating a smoother experience.

**Implementation**:
```python
embedder_ready = models_data.get("embedder", {}).get("status") == "ready"
st.file_uploader(..., disabled=not embedder_ready,
    help="Upload documents" if embedder_ready else "Embedder model is loading — please wait")
st.button("Upload", ..., disabled=not embedder_ready)
```

## Risks / Trade-offs

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `snapshot_download` callback fires in a thread, can't call async `state.update()` directly | High | Use `asyncio.run_coroutine_threadsafe()` with a reference to the main event loop |
| Embedder warmup adds ~1-30s to startup time (was previously lazy) | Medium | Trade-off for gating: users see progress instead of silent blocking. Embedder load is already happening — this just makes it visible and async |
| `permanent_error` state may never be reached if transient errors keep resetting | Low | The 5-consecutive-30s-cap heuristic is conservative. Could also add a wall-clock timeout (e.g., 10 minutes total retry time) |
| Frontend polling creates continuous HTTP traffic during warmup | Low | Single user, 200ms interval, lightweight JSON response. Negligible |
| Upload rejected during embedder warmup may frustrate users | Medium | Upload is a synchronous action — users expect to wait for something that takes seconds. Progress bar + tooltip ("Embedder still initializing...") manages expectations |
| LangChain route currently checks cross-encoder error only — needs alignment with new gate | Low | Gate replaces the ad-hoc check. Remove the existing cross-encoder check from `/langchain` routes |
| Streaming endpoints (SSE) need early-abort on 503 — can't use standard `Depends` pattern as easily | Medium | Apply `require_models` check inside the stream generator at the very top, before yielding any data. Same logic, just not via `Depends` |
| Documents page has an inline model check that will diverge from the new architecture | Medium | Replace it with a shared model status component that both Chat and Documents pages import, ensuring consistent behavior |
