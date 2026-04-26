from .auth import router as auth_router
from .documents import router as documents_router
from .query import router as query_router
from .cache import router as cache_router
from .health import router as health_router

__all__ = [
    "auth_router",
    "documents_router",
    "query_router",
    "cache_router",
    "health_router",
]
