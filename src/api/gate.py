"""Model readiness gate for FastAPI endpoints.

Provides the ``require_models`` dependency that checks model warmup state
and returns 503 if required models are not ready.
"""

import logging
from collections.abc import Awaitable, Callable
from fastapi import HTTPException, status

from ..domain.services.warmup import get_warmup_state

logger = logging.getLogger(__name__)

# Set of known valid model names for input validation
_VALID_MODELS = frozenset({"llm", "cross_encoder", "embedder", "dspy_lm"})

# A mapping from model status to a user-facing description
_STATUS_DESCRIPTIONS = {
    "loading": "is still loading",
    "error": "encountered an error — auto-retrying",
    "permanent_error": "has permanently failed — manual restart required",
}


def require_models(*model_names: str) -> Callable[[], Awaitable[None]]:
    """Factory that returns a FastAPI dependency for model readiness check.

    Usage::

        @router.post("/query")
        async def query(..., _: None = Depends(require_models("llm"))):
            ...

        @router.post("/query/langchain")
        async def query_langchain(..., _: None = Depends(require_models("llm", "cross_encoder"))):
            ...

    The returned callable raises ``HTTPException(503)`` with a
    ``Retry-After`` header if any required model is not ready.
    """

    async def _dependency() -> None:
        state = get_warmup_state()

        for model_name in model_names:
            if model_name not in _VALID_MODELS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown model '{model_name}'",
                )

            status_obj = await state.get_status(model_name)
            if status_obj is None:
                # Model not registered — it's probably still initialising
                detail = f"Model '{model_name}' is not yet available"
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=detail,
                    headers={"Retry-After": "5"},
                )

            if status_obj.status != "ready":
                desc = _STATUS_DESCRIPTIONS.get(
                    status_obj.status,
                    f"is in unknown state '{status_obj.status}'",
                )
                detail = f"Model '{model_name}' {desc}"
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=detail,
                    headers={"Retry-After": "5"},
                )

        return None

    return _dependency
