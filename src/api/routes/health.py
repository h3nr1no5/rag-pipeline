import time
import logging
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
        from ...domain.services.llm import get_llm_stats, _llm_instance
        llm_stats = get_llm_stats()
        llm_loading = _llm_instance is not None and _llm_instance._model is None and _llm_instance._model_loaded
    except Exception:
        pass
    
    embedder_stats = {}
    embedder_loading = False
    try:
        from ...domain.services.embedding import get_embedder_stats, _embedder_instance
        embedder_stats = get_embedder_stats()
        embedder_loading = _embedder_instance is None
    except Exception:
        pass
    
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
    try:
        from ...domain.services.llm import _llm_instance
        llm_ready = _llm_instance is not None and getattr(_llm_instance, "_model_loaded", False)
    except Exception:
        pass
    try:
        from ...domain.services.embedding import _embedder_instance
        embedder_ready = _embedder_instance is not None
    except Exception:
        pass

    return {
        "llm": {"status": "ready" if llm_ready else "loading"},
        "embedder": {"status": "ready" if embedder_ready else "loading"},
    }


@router.get("/")
async def root():
    return {
        "service": "RAG Pipeline API",
        "version": "1.0.0",
        "docs": "/docs",
    }
