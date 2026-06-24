"""Unit tests for ``require_models`` — FastAPI dependency factory that gates
endpoints behind model readiness.

``require_models`` is a **factory** that returns a callable dependency::

    dep = require_models("llm")          # returns an async callable
    result = await dep()                  # executes the readiness check

Covers Tasks 13.7–13.8:

- ``require_models()`` returns ``None`` when all named models are ready.
- Raises ``HTTPException(503)`` when any model is missing, loading,
  in error state, or in permanent_error state.
- Verifies the ``Retry-After`` header is set.
"""

import pytest
from fastapi import HTTPException
from src.api.gate import require_models
from src.domain.services.warmup import WarmupState, ModelStatus, get_warmup_state


@pytest.fixture(autouse=True)
def reset_warmup():
    """Clear the singleton's model registry before each test."""
    state = get_warmup_state()
    state._models.clear()


# =========================================================================
# Success case
# =========================================================================


@pytest.mark.asyncio
async def test_require_models_all_ready():
    """Returns ``None`` when all required models are in 'ready' status."""
    state = get_warmup_state()
    await state.update("llm", status="ready")
    await state.update("cross_encoder", status="ready")

    dep = require_models("llm", "cross_encoder")
    result = await dep()
    assert result is None


@pytest.mark.asyncio
async def test_require_models_single_ready():
    """Single model ready → returns ``None``."""
    state = get_warmup_state()
    await state.update("llm", status="ready")

    dep = require_models("llm")
    result = await dep()
    assert result is None


# =========================================================================
# Missing / unregistered model
# =========================================================================


@pytest.mark.asyncio
async def test_require_models_missing_model():
    """Unknown model name → 400 with 'Unknown model' detail."""
    dep = require_models("nonexistent")
    with pytest.raises(HTTPException) as exc_info:
        await dep()
    assert exc_info.value.status_code == 400
    assert "Unknown model" in exc_info.value.detail


@pytest.mark.asyncio
async def test_require_models_one_missing_among_several():
    """If one of several required models is missing → 503."""
    state = get_warmup_state()
    await state.update("llm", status="ready")
    # "cross_encoder" not registered

    dep = require_models("llm", "cross_encoder")
    with pytest.raises(HTTPException) as exc_info:
        await dep()
    assert exc_info.value.status_code == 503
    assert "cross_encoder" in exc_info.value.detail


# =========================================================================
# Loading state
# =========================================================================


@pytest.mark.asyncio
async def test_require_models_loading():
    """Model in 'loading' status → 503 with 'still loading'."""
    state = get_warmup_state()
    await state.update("llm", status="loading")

    dep = require_models("llm")
    with pytest.raises(HTTPException) as exc_info:
        await dep()
    assert exc_info.value.status_code == 503
    assert "loading" in exc_info.value.detail.lower()


# =========================================================================
# Error state
# =========================================================================


@pytest.mark.asyncio
async def test_require_models_error():
    """Model in 'error' status → 503 with auto-retry message."""
    state = get_warmup_state()
    await state.update("llm", status="error")

    dep = require_models("llm")
    with pytest.raises(HTTPException) as exc_info:
        await dep()
    assert exc_info.value.status_code == 503
    assert "error" in exc_info.value.detail.lower()


# =========================================================================
# Permanent error state
# =========================================================================


@pytest.mark.asyncio
async def test_require_models_permanent_error():
    """Model in 'permanent_error' status → 503 with manual-restart message."""
    state = get_warmup_state()
    await state.update("llm", status="permanent_error")

    dep = require_models("llm")
    with pytest.raises(HTTPException) as exc_info:
        await dep()
    assert exc_info.value.status_code == 503
    assert "permanent" in exc_info.value.detail.lower()


# =========================================================================
# Retry-After header
# =========================================================================


@pytest.mark.asyncio
async def test_require_models_retry_after_header_loading():
    """503 response includes ``Retry-After: 5`` header when loading."""
    state = get_warmup_state()
    await state.update("llm", status="loading")

    dep = require_models("llm")
    with pytest.raises(HTTPException) as exc_info:
        await dep()
    assert exc_info.value.headers.get("Retry-After") == "5"


@pytest.mark.asyncio
async def test_require_models_retry_after_header_missing():
    """Unknown model name → 400 without Retry-After header."""
    dep = require_models("ghost")
    with pytest.raises(HTTPException) as exc_info:
        await dep()
    assert exc_info.value.status_code == 400
    # 400 BAD_REQUEST does not include Retry-After
    assert "Retry-After" not in (exc_info.value.headers or {})


@pytest.mark.asyncio
async def test_require_models_retry_after_header_error():
    """503 response includes ``Retry-After: 5`` for errored model."""
    state = get_warmup_state()
    await state.update("llm", status="error")

    dep = require_models("llm")
    with pytest.raises(HTTPException) as exc_info:
        await dep()
    assert exc_info.value.headers.get("Retry-After") == "5"


# =========================================================================
# Unknown / unexpected status
# =========================================================================


@pytest.mark.asyncio
async def test_require_models_unknown_status():
    """Model with an unexpected status string gets a generic 503."""
    state = get_warmup_state()
    await state.update("llm", status="unknown_status_xyz")

    dep = require_models("llm")
    with pytest.raises(HTTPException) as exc_info:
        await dep()
    assert exc_info.value.status_code == 503
    assert "unknown" in exc_info.value.detail
