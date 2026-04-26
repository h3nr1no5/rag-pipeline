# Re-export for backward compatibility
from .routes import router
from ._helpers import deduplicate_chunks, build_prompt, clean_response, check_cache
from ._retrieval import retrieve_chunks

__all__ = [
    "router",
    "deduplicate_chunks",
    "build_prompt",
    "clean_response",
    "check_cache",
    "retrieve_chunks",
]