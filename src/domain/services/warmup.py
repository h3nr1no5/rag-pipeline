"""Model warmup state tracking and startup loading."""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelStatus:
    """Per-model loading status.

    Status values: "loading", "ready", "error", "permanent_error"
    """
    model: str = ""
    status: str = "loading"
    progress: int = 0
    error: Optional[str] = None
    message: str = ""


class WarmupState:
    """Singleton tracking warmup state for all models."""

    _instance = None
    _singleton_lock = threading.Lock()
    _lock: asyncio.Lock
    _models: dict[str, ModelStatus]

    def __new__(cls):
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._models = {}
                    cls._instance._lock = asyncio.Lock()
        return cls._instance

    async def update(self, model_name: str, **kwargs):
        async with self._lock:
            if model_name not in self._models:
                self._models[model_name] = ModelStatus()
            for k, v in kwargs.items():
                setattr(self._models[model_name], k, v)

    async def get_status(self, model_name: str) -> Optional[ModelStatus]:
        async with self._lock:
            return self._models.get(model_name)

    async def to_dict(self, sanitize_errors: bool = True) -> dict:
        async with self._lock:
            result = {}
            for name, status in self._models.items():
                entry = {
                    "status": status.status,
                    "model": status.model,
                    "progress": status.progress,
                    "error": status.error,
                    "message": status.message,
                }
                if sanitize_errors:
                    if entry["error"] is not None:
                        entry["error"] = "Model failed to load"
                    if status.status in ("error", "permanent_error"):
                        entry["message"] = "An error occurred. Please check server logs."
                result[name] = entry
            return result

    @property
    def all_ready(self) -> bool:
        if not self._models:
            return False
        return all(s.status == "ready" for s in self._models.values())

    @property
    def any_loading(self) -> bool:
        return any(s.status == "loading" for s in self._models.values())


_warmup_state = WarmupState()


def get_warmup_state() -> WarmupState:
    return _warmup_state


def _make_progress_callback(model_name: str, state: WarmupState, loop: asyncio.AbstractEventLoop):
    """Return a callback for snapshot_download that updates WarmupState via the event loop.

    The returned callback can be passed to ``huggingface_hub.snapshot_download()`` as the
    ``callback`` parameter. It receives ``(stage, current, total, status)`` tuples and
    schedules ``WarmupState.update()`` coroutines on the given event loop.
    """
    def progress_callback(stage, current, total, status):
        stage_str = str(stage) if not isinstance(stage, str) else stage

        if "start" in stage_str.lower():
            coro = state.update(model_name, message="Starting download...", progress=5)
        elif "download" in stage_str.lower() and total and total > 0:
            pct = min(int(5 + (current / total) * 80), 85)
            mb_done = int(current / 1024 / 1024)
            mb_total = int(total / 1024 / 1024)
            coro = state.update(
                model_name,
                message=f"Downloading... {mb_done}MB / {mb_total}MB",
                progress=pct,
            )
        elif "extract" in stage_str.lower():
            coro = state.update(model_name, message="Extracting model files...", progress=85)
        else:
            return  # don't update for other stages

        asyncio.run_coroutine_threadsafe(coro, loop)

    return progress_callback


async def _retry_with_backoff(
    model_name: str,
    state: WarmupState,
    load_fn,
    retry_count: int = 0,
    max_retries: int = 5,
):
    """Retry model loading with exponential backoff.

    Backoff: delay = min(30, 2 * 2^retry_count) seconds.
    After max_retries, escalate to permanent_error.
    """
    if retry_count >= max_retries:
        await state.update(
            model_name,
            status="permanent_error",
            error=f"Failed after {max_retries} retries",
            message="Permanent failure — manual restart required",
        )
        logger.error(f"{model_name} failed after {max_retries} retries, marked permanent_error")
        return

    delay = min(30, 2 * (2**retry_count))
    await state.update(
        model_name,
        status="loading",
        progress=0,
        message=f"Retrying in {delay}s (attempt {retry_count + 1}/{max_retries})...",
    )

    logger.info(f"Retrying {model_name} in {delay}s (attempt {retry_count + 1}/{max_retries})")
    await asyncio.sleep(delay)

    try:
        await state.update(
            model_name,
            message=f"Loading (attempt {retry_count + 1}/{max_retries})...",
            progress=10,
        )
        await load_fn()
        await state.update(model_name, status="ready", progress=100, message="Ready")
        logger.info(f"{model_name} loaded successfully on retry {retry_count + 1}")
    except Exception as e:
        logger.error(f"{model_name} failed on retry {retry_count + 1}: {e}")
        # Schedule next retry
        asyncio.create_task(
            _retry_with_backoff(model_name, state, load_fn, retry_count + 1, max_retries)
        )


async def warmup_models():
    """Preload cross-encoder and LLM models on startup (non-blocking)."""
    _event_loop = asyncio.get_event_loop()
    state = get_warmup_state()
    from ...core.config import get_settings

    # Initialize model registry entries
    state._models["cross_encoder"] = ModelStatus()
    state._models["llm"] = ModelStatus()
    state._models["embedder"] = ModelStatus()
    state._models["dspy_lm"] = ModelStatus()

    # --- Cross-encoder ---
    await state.update("cross_encoder", status="loading", progress=0)

    async def _load_cross_encoder():
        settings = get_settings()
        from .retrieval_langchain import CrossEncoderReRanker

        # Pre-download cross-encoder model with progress tracking
        try:
            from huggingface_hub import snapshot_download

            ce_callback = _make_progress_callback("cross_encoder", state, _event_loop)
            await state.update("cross_encoder", message="Downloading cross-encoder model...", progress=2)
            await asyncio.to_thread(snapshot_download, settings.reranker_model, callback=ce_callback)
            await state.update("cross_encoder", message="Cross-encoder downloaded, loading...", progress=90)
        except Exception:
            logger.warning("Pre-download of cross-encoder failed, will load directly")

        await state.update("cross_encoder", model=settings.reranker_model, progress=50)
        reranker = CrossEncoderReRanker()
        await asyncio.wait_for(reranker._ensure_model(), timeout=120)

    try:
        await _load_cross_encoder()
        await state.update("cross_encoder", status="ready", progress=100, message="Ready")
        logger.info("Cross-encoder warmup complete")
    except TimeoutError:
        await state.update("cross_encoder", status="error", error="Cross-encoder timed out (120s)")
        logger.error("Cross-encoder warmup timed out")
        asyncio.create_task(_retry_with_backoff("cross_encoder", state, _load_cross_encoder))
    except Exception as e:
        await state.update("cross_encoder", status="error", error=str(e))
        logger.error(f"Cross-encoder warmup failed: {e}")
        asyncio.create_task(_retry_with_backoff("cross_encoder", state, _load_cross_encoder))

    # --- LLM ---
    await state.update("llm", status="loading", progress=0)

    async def _load_llm():
        settings = get_settings()
        from .llm import get_llm

        # Pre-download LLM with progress tracking
        try:
            from huggingface_hub import snapshot_download

            llm_callback = _make_progress_callback("llm", state, _event_loop)
            await state.update("llm", message="Downloading LLM...", progress=2)
            model_path_llm = settings.llm_model
            if not model_path_llm.startswith("mlx-community/"):
                model_path_llm = f"mlx-community/{model_path_llm}"
            await asyncio.to_thread(snapshot_download, model_path_llm, callback=llm_callback)
            await state.update("llm", message="LLM downloaded, loading...", progress=90)
        except Exception:
            logger.warning("Pre-download of LLM failed, will load directly")

        await state.update("llm", model=settings.llm_model, progress=50)
        llm = await get_llm()

        def _load_llm_sync():
            llm._ensure_model_loaded()
            return llm

        await asyncio.wait_for(asyncio.to_thread(_load_llm_sync), timeout=120)

    try:
        await _load_llm()
        await state.update("llm", status="ready", progress=100, message="Ready")
        logger.info("LLM warmup complete")
    except TimeoutError:
        await state.update("llm", status="error", error="LLM loading timed out (120s)")
        logger.error("LLM warmup timed out")
        asyncio.create_task(_retry_with_backoff("llm", state, _load_llm))
    except Exception as e:
        await state.update("llm", status="error", error=str(e))
        logger.error(f"LLM warmup failed: {e}")
        asyncio.create_task(_retry_with_backoff("llm", state, _load_llm))

    # --- Embedder ---
    await state.update("embedder", status="loading", progress=0)

    async def _load_embedder():
        settings = get_settings()

        # Pre-download embedding model with progress tracking
        try:
            from huggingface_hub import snapshot_download

            emb_callback = _make_progress_callback("embedder", state, _event_loop)
            await state.update("embedder", message="Downloading embedding model...", progress=2)
            await asyncio.to_thread(snapshot_download, settings.embedding_model, callback=emb_callback)
            await state.update("embedder", message="Embedding model downloaded, loading...", progress=90)
        except Exception:
            logger.warning("Pre-download of embedding model failed, will load directly")

        await state.update("embedder", model=settings.embedding_model, progress=30)
        logger.info("Starting embedder warmup...")

        from .embedding import SentenceTransformerEmbedder

        def _load_embedder_sync():
            try:
                embedder = SentenceTransformerEmbedder()
                return embedder
            except Exception as e:
                logger.error(f"Embedder model loading failed inside thread: {e}")
                raise

        await state.update("embedder", message="Loading embedding model...", progress=60)

        embedder = await asyncio.wait_for(
            asyncio.to_thread(_load_embedder_sync), timeout=120
        )

        # Set global embedder instance so get_embedder() returns it immediately
        from . import embedding as emb_mod

        emb_mod._embedder_instance = embedder
        emb_mod._embedder_load_time = time.time() - 0  # approximate

    try:
        await _load_embedder()
        await state.update("embedder", status="ready", progress=100, message="Embedding model ready")
        logger.info("Embedder warmup complete")
    except TimeoutError:
        await state.update("embedder", status="error", error="Embedder timed out (120s)")
        logger.error("Embedder warmup timed out")
        asyncio.create_task(_retry_with_backoff("embedder", state, _load_embedder))
    except Exception as e:
        await state.update("embedder", status="error", error=str(e))
        logger.error(f"Embedder warmup failed: {e}")
        asyncio.create_task(_retry_with_backoff("embedder", state, _load_embedder))

    # Warmup DSPy LM (instant — adapter wraps existing LLM)
    try:
        _settings = get_settings()
        if _settings.api_docs_enabled:
            await state.update("dspy_lm", model="dspy-lm-adapter", status="loading", progress=0)

            from ..rag.api_docs.pipeline.lm_adapter import get_mlx_dspy_lm
            import dspy

            mlx_dspy_lm = get_mlx_dspy_lm()
            dspy.configure(lm=mlx_dspy_lm)

            await state.update("dspy_lm", status="ready", progress=100, message="DSPy LM adapter ready")
            logger.info("DSPy LM warmup complete")
        else:
            await state.update(
                "dspy_lm",
                status="ready",
                progress=100,
                message="DSPy LM not required (api_docs_enabled=False)",
            )
            logger.info("DSPy LM warmup skipped (api_docs_enabled=False)")
    except Exception as e:
        await state.update("dspy_lm", status="error", error=str(e))
        logger.error(f"DSPy LM warmup failed: {e}")
