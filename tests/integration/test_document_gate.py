"""Integration tests for the ``require_models`` gate on document endpoints.

Covers Tasks 13.11 & 13.12:

- ``POST /documents`` is gated by ``require_models("embedder")`` and
  returns ``503 Service Unavailable`` when the embedder is not ready.
- ``GET /documents`` does **not** gate on model readiness and should
  return ``200`` (or at least not ``503``) even when the embedder is
  still loading.
"""

import pytest
from fastapi import status

from src.domain.services.warmup import get_warmup_state, ModelStatus


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _set_warmup(models: dict[str, str]):
    """Replace the warmup state with entries having given statuses.

    Parameters
    ----------
    models:
        Mapping of model_name → status string (e.g. ``{"embedder": "loading"}``).
    """
    state = get_warmup_state()
    state._models.clear()
    for name, stat in models.items():
        state._models[name] = ModelStatus(
            status=stat, progress=100 if stat == "ready" else 50
        )


# =========================================================================
# Task 13.11 — Document upload gated by embedder readiness
# =========================================================================


@pytest.mark.asyncio
async def test_upload_document_returns_503_when_embedder_loading(auth_client):
    """``POST /documents`` → 503 when embedder is still loading."""
    _set_warmup({"embedder": "loading"})

    response = await auth_client.post(
        "/api/v1/documents",
        files={"file": ("test.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert "detail" in data
    assert "embedder" in data["detail"]
    assert "loading" in data["detail"].lower()


@pytest.mark.asyncio
async def test_upload_document_returns_503_when_embedder_error(auth_client):
    """``POST /documents`` → 503 when embedder is in error status."""
    _set_warmup({"embedder": "error"})

    response = await auth_client.post(
        "/api/v1/documents",
        files={"file": ("test.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert "detail" in data
    assert "embedder" in data["detail"]
    assert "error" in data["detail"].lower()


@pytest.mark.asyncio
async def test_upload_document_returns_503_when_embedder_permanent_error(auth_client):
    """``POST /documents`` → 503 when embedder has permanent_error."""
    _set_warmup({"embedder": "permanent_error"})

    response = await auth_client.post(
        "/api/v1/documents",
        files={"file": ("test.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    data = response.json()
    assert "detail" in data
    assert "embedder" in data["detail"]
    assert "permanent" in data["detail"].lower()


@pytest.mark.asyncio
async def test_upload_document_returns_503_when_embedder_missing(auth_client):
    """``POST /documents`` → 503 when embedder is not registered at all."""
    _set_warmup({})  # no embedder registered

    response = await auth_client.post(
        "/api/v1/documents",
        files={"file": ("test.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


# =========================================================================
# Task 13.12 — Document list endpoint does NOT require model readiness
# =========================================================================


@pytest.mark.asyncio
async def test_list_documents_returns_200_when_embedder_loading(auth_client):
    """``GET /documents`` returns 200 (not 503) even when embedder is loading."""
    _set_warmup({"embedder": "loading", "llm": "ready", "cross_encoder": "ready"})

    response = await auth_client.get("/api/v1/documents")
    # The endpoint should work without the embedder being ready
    assert response.status_code != status.HTTP_503_SERVICE_UNAVAILABLE
    # Expect a normal response (200, possibly with empty document list)
    assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
