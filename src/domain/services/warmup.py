"""Model warmup state tracking and startup loading."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelStatus:
    """Per-model loading status."""
    model: str = ""
    status: str = "loading"  # "loading", "ready", "error"
    progress: int = 0
    error: Optional[str] = None


class WarmupState:
    """Singleton tracking warmup state for all models."""

    _instance = None
    _lock: asyncio.Lock
    cross_encoder: ModelStatus
    llm: ModelStatus

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.cross_encoder = ModelStatus()
            cls._instance.llm = ModelStatus()
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    async def update_cross_encoder(self, **kwargs):
        async with self._lock:
            for k, v in kwargs.items():
                setattr(self.cross_encoder, k, v)

    async def update_llm(self, **kwargs):
        async with self._lock:
            for k, v in kwargs.items():
                setattr(self.llm, k, v)

    async def to_dict(self, sanitize_errors: bool = True) -> dict:
        async with self._lock:
            result = {
                "cross_encoder": {
                    "status": self.cross_encoder.status,
                    "model": self.cross_encoder.model,
                    "progress": self.cross_encoder.progress,
                    "error": self.cross_encoder.error,
                },
                "llm": {
                    "status": self.llm.status,
                    "model": self.llm.model,
                    "progress": self.llm.progress,
                    "error": self.llm.error,
                },
            }
            if sanitize_errors:
                for key in ("cross_encoder", "llm"):
                    if result[key]["error"] is not None:
                        result[key]["error"] = "Model failed to load"
            return result

    @property
    def all_ready(self) -> bool:
        return (self.cross_encoder.status == "ready" and
                self.llm.status == "ready")

    @property
    def any_loading(self) -> bool:
        return (self.cross_encoder.status == "loading" or
                self.llm.status == "loading")


_warmup_state = WarmupState()


def get_warmup_state() -> WarmupState:
    return _warmup_state


async def warmup_models():
    """Preload cross-encoder and LLM models on startup (non-blocking)."""
    state = get_warmup_state()

    # Warmup cross-encoder
    await state.update_cross_encoder(status="loading", progress=0)

    try:
        # Import cross-encoder from retrieval_langchain module
        from .retrieval_langchain import CrossEncoderReRanker

        await state.update_cross_encoder(model="Alibaba-NLP/gte-reranker-modernbert-base", progress=50)

        reranker = CrossEncoderReRanker()
        # This triggers _ensure_model which now uses asyncio.to_thread
        await reranker._ensure_model()

        await state.update_cross_encoder(status="ready", progress=100)
        logger.info("Cross-encoder warmup complete")
    except Exception as e:
        await state.update_cross_encoder(status="error", error=str(e))
        logger.error(f"Cross-encoder warmup failed: {e}")

    # Warmup LLM
    await state.update_llm(status="loading", progress=0)

    try:
        from .llm import get_llm

        await state.update_llm(model="mlx-community/Qwen2.5-1.5B-Instruct-4bit", progress=50)

        llm = await get_llm()
        # The LLM is loaded lazily inside get_llm, so call generate with a dummy prompt
        # to trigger the actual loading. Run in to_thread to keep event loop free.

        def _load_llm_sync():
            # Trigger ensure_model_loaded synchronously via __init__
            llm._ensure_model_loaded()
            return llm

        await asyncio.to_thread(_load_llm_sync)

        await state.update_llm(status="ready", progress=100)
        logger.info("LLM warmup complete")
    except Exception as e:
        await state.update_llm(status="error", error=str(e))
        logger.error(f"LLM warmup failed: {e}")
