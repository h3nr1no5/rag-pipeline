import logging
import time

from fastapi import APIRouter

router = APIRouter(tags=["Health"])

logger = logging.getLogger(__name__)

_start_time = time.time()


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "rag-pipeline"}


@router.get("/health/detailed")
async def detailed_health():
    uptime = int(time.time() - _start_time)

    llm_stats = {}
    llm_loading = False
    try:
        from ...domain.services.llm import _llm_instance, get_llm_stats
        llm_stats = get_llm_stats()
        llm_loading = _llm_instance is not None and _llm_instance._model is None and _llm_instance._model_loaded
    except Exception:
        logger.exception("Failed to get LLM stats:")

    embedder_stats = {}
    embedder_loading = False
    try:
        from ...domain.services.embedding import _embedder_instance, get_embedder_stats
        embedder_stats = get_embedder_stats()
        embedder_loading = _embedder_instance is None
    except Exception:
        logger.exception("Failed to get embedder stats:")

    return {
        "status": "healthy",
        "service": "rag-pipeline",
        "version": "1.0.0",
        "uptime_seconds": uptime,
        "models_loading": llm_loading or embedder_loading,
        "llm": llm_stats,
        "embedder": embedder_stats,
    }


@router.get("/health/models")
async def models_health():
    """Return per-model loading status by checking singletons directly."""
    llm_ready = False
    embedder_ready = False
    cross_encoder_ready = False
    try:
        from ...domain.services.llm import _llm_instance
        llm_ready = _llm_instance is not None and getattr(_llm_instance, "_model", None) is not None
    except Exception:
        logger.exception("Failed to check LLM model status:")
    try:
        from ...domain.services.embedding import _embedder_instance
        embedder_ready = _embedder_instance is not None
    except Exception:
        logger.exception("Failed to check embedder model status:")
    try:
        from ...domain.services.retrieval_langchain import CrossEncoderReRanker
        cross_encoder_ready = (
            CrossEncoderReRanker._instance is not None
            and CrossEncoderReRanker._instance._model is not None
        )
    except Exception:
        logger.exception("Failed to check cross-encoder model status:")

    result = {
        "llm": {"status": "ready" if llm_ready else "loading"},
        "embedder": {"status": "ready" if embedder_ready else "loading"},
        "cross_encoder": {"status": "ready" if cross_encoder_ready else "loading"},
    }

    try:
        from ...core.config import get_settings
        if get_settings().api_docs_enabled:
            from ...domain.rag.api_docs.pipeline.lm_adapter import _dspy_lm_instance
            dspy_lm_ready = _dspy_lm_instance is not None
            result["dspy_lm"] = {"status": "ready" if dspy_lm_ready else "loading"}
    except Exception:
        logger.exception("Failed to check DSPy LM status:")

    return result


@router.get("/")
async def root():
    return {
        "service": "RAG Pipeline API",
        "version": "1.0.0",
        "docs": "/docs",
    }
