"""Integration tests for the ``require_models`` gate via HTTP.

Covers Task 13.10 — verifies that query endpoints return ``503 Service
Unavailable`` when required models are not in the 'ready' state.

These tests use the ``auth_client`` fixture (from ``tests/integration/
conftest.py``) so that the auth dependency passes and the gate is
reached.  The warmup singleton is manipulated directly in each test to
simulate different model-readiness scenarios.
"""

import pytest
from fastapi import status

from src.domain.services.warmup import WarmupState, ModelStatus, get_warmup_state


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _set_warmup(models: dict[str, str]):
    """Replace the warmup state with entries having given statuses.

    Parameters
    ----------
    models:
        Mapping of model_name → status string (e.g. ``{"llm": "loading"}``).
    """
    state = get_warmup_state()
    state._models.clear()
    for name, stat in models.items():
        state._models[name] = ModelStatus(status=stat, progress=100 if stat == "ready" else 50)


@pytest.mark.asyncio
async def test_query_returns_503_when_llm_loading(auth_client):
    """``POST /query`` → 503 when LLM is still loading."""
    _set_warmup({"llm": "loading", "cross_encoder": "ready"})

    response = await auth_client.post(
        "/api/v1/query",
        json={"question": "test", "document_ids": ["nonexistent-id"]},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_query_returns_503_when_llm_missing(auth_client):
    """``POST /query`` → 503 when LLM is not registered at all."""
    _set_warmup({"cross_encoder": "ready"})  # llm absent

    response = await auth_client.post(
        "/api/v1/query",
        json={"question": "test", "document_ids": ["nonexistent-id"]},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_query_returns_503_when_llm_errored(auth_client):
    """``POST /query`` → 503 when LLM is in error status."""
    _set_warmup({"llm": "error", "cross_encoder": "ready"})

    response = await auth_client.post(
        "/api/v1/query",
        json={"question": "test", "document_ids": ["nonexistent-id"]},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_query_returns_503_when_llm_permanent_error(auth_client):
    """``POST /query`` → 503 when LLM has permanent_error."""
    _set_warmup({"llm": "permanent_error", "cross_encoder": "ready"})

    response = await auth_client.post(
        "/api/v1/query",
        json={"question": "test", "document_ids": ["nonexistent-id"]},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_query_stream_returns_503_when_llm_loading(auth_client):
    """``POST /query/stream`` → 503 when LLM is loading."""
    _set_warmup({"llm": "loading", "cross_encoder": "ready"})

    response = await auth_client.post(
        "/api/v1/query/stream",
        json={"question": "test", "document_ids": ["nonexistent-id"]},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_query_langchain_returns_503_when_models_loading(auth_client):
    """``POST /query/langchain`` requires both 'llm' and 'cross_encoder';
    returns 503 when either is not ready."""
    _set_warmup({"llm": "ready", "cross_encoder": "loading"})

    response = await auth_client.post(
        "/api/v1/query/langchain",
        json={"question": "test", "document_ids": ["nonexistent-id"]},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_query_langchain_stream_returns_503_when_models_loading(auth_client):
    """``POST /query/langchain/stream`` → 503 when cross_encoder is loading."""
    _set_warmup({"llm": "loading", "cross_encoder": "ready"})

    response = await auth_client.post(
        "/api/v1/query/langchain/stream",
        json={"question": "test", "document_ids": ["nonexistent-id"]},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_query_llamaindex_returns_503_when_llm_loading(auth_client):
    """``POST /query/llamaindex`` → 503 when LLM is loading."""
    _set_warmup({"llm": "loading"})

    response = await auth_client.post(
        "/api/v1/query/llamaindex",
        json={"question": "test", "document_ids": ["nonexistent-id"]},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_query_llamaindex_stream_returns_503_when_llm_loading(auth_client):
    """``POST /query/llamaindex/stream`` → 503 when LLM is loading."""
    _set_warmup({"llm": "loading"})

    response = await auth_client.post(
        "/api/v1/query/llamaindex/stream",
        json={"question": "test", "document_ids": ["nonexistent-id"]},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
