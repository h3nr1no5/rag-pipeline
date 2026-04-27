import time
import logging
from fastapi import APIRouter
from ...core.config import get_settings

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
    
    models_ready = not llm_loading and not embedder_loading
    
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
    from ...domain.services.llm import _llm_instance, get_llm, _llm_load_status
    from ...domain.services.embedding import _embedder_instance, get_embedder
    
    llm_status = "not_started"
    llm_model = None
    llm_progress = ""
    llm_error = None
    
    try:
        if _llm_instance is not None and hasattr(_llm_instance, '_model'):
            if _llm_instance._model is not None:
                llm_status = "ready"
                llm_model = _llm_instance.get_model_name()
            elif _llm_instance._model_loaded:
                llm_status = _llm_load_status
                llm_model = _llm_instance.get_model_name()
                if _llm_load_status == "idle":
                    llm_status = "downloading"
                    llm_progress = "Initializing LLM..."
                    _llm_instance._ensure_model_loaded()
                    llm_status = "ready"
                    llm_model = _llm_instance.get_model_name()
        else:
            llm_status = "downloading"
            llm_progress = "Creating LLM instance..."
            await get_llm()
            if _llm_instance and _llm_instance._model is not None:
                llm_status = "ready"
                llm_model = _llm_instance.get_model_name()
    except Exception as e:
        llm_status = "error"
        llm_error = str(e)
    
    embedder_status = "not_loaded"
    embedder_model = None
    embedder_dimension = None
    embedder_progress = ""
    
    try:
        if _embedder_instance is not None and hasattr(_embedder_instance, 'get_model_name'):
            embedder_status = "ready"
            embedder_model = _embedder_instance.get_model_name()
            embedder_dimension = _embedder_instance.get_dimension()
        else:
            embedder_status = "downloading"
            embedder_progress = "Loading embedder..."
            await get_embedder()
            if _embedder_instance:
                embedder_model = _embedder_instance.get_model_name()
                embedder_dimension = _embedder_instance.get_dimension()
                embedder_status = "ready"
    except Exception as e:
        embedder_status = "error"
        embedder_progress = f"Error: {str(e)[:50]}"
    
    all_ready = llm_status == "ready" and embedder_status == "ready"
    
    settings = get_settings()
    
    return {
        "llm": {
            "status": llm_status,
            "model": llm_model,
            "progress": llm_progress,
            "error": llm_error,
        },
        "embedder": {
            "status": embedder_status,
            "model": embedder_model,
            "dimension": embedder_dimension,
            "progress": embedder_progress,
        },
        "all_ready": all_ready,
    }


@router.get("/")
async def root():
    return {
        "service": "RAG Pipeline API",
        "version": "1.0.0",
        "docs": "/docs",
    }
