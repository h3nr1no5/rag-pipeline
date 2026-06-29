"""Integration tests for the debug logging toggle endpoint.

Covers:
- GET /api/v1/debug/logging — return current overrides
- PUT /api/v1/debug/logging — set / clear overrides
- Auth protection on both endpoints
- Invalid level validation (422)
"""
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.logging import LogLevelManager


@pytest.fixture(autouse=True)
def reset_overrides():
    """Reset LogLevelManager before each test."""
    LogLevelManager().reset()
    yield


# ---------------------------------------------------------------------------
# GET /api/v1/debug/logging
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_logging_returns_empty_initially(auth_client):
    """GET returns empty overrides when none are set."""
    resp = await auth_client.get("/api/v1/debug/logging")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overrides"] == {}


@pytest.mark.asyncio
async def test_get_after_put_returns_override(auth_client):
    """GET returns the override that was set via PUT."""
    await auth_client.put(
        "/api/v1/debug/logging",
        json={"overrides": {"src.domain.services.retrieval": "DEBUG"}},
    )
    resp = await auth_client.get("/api/v1/debug/logging")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overrides"].get("src.domain.services.retrieval") == "DEBUG"


# ---------------------------------------------------------------------------
# PUT /api/v1/debug/logging
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_sets_logging_override(auth_client):
    """PUT sets a log level override and GET returns it."""
    put_resp = await auth_client.put(
        "/api/v1/debug/logging",
        json={"overrides": {"src.domain.services.retrieval": "DEBUG"}},
    )
    assert put_resp.status_code == 200
    data = put_resp.json()
    assert data["overrides"].get("src.domain.services.retrieval") == "DEBUG"

    # Verify via GET
    get_resp = await auth_client.get("/api/v1/debug/logging")
    assert get_resp.json()["overrides"].get("src.domain.services.retrieval") == "DEBUG"


@pytest.mark.asyncio
async def test_put_with_null_clears_override(auth_client):
    """PUT with null clears the override."""
    # Set an override
    await auth_client.put(
        "/api/v1/debug/logging",
        json={"overrides": {"src.domain.services.retrieval": "DEBUG"}},
    )
    # Clear it
    put_resp = await auth_client.put(
        "/api/v1/debug/logging",
        json={"overrides": {"src.domain.services.retrieval": None}},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["overrides"] == {}


# ---------------------------------------------------------------------------
# Auth protection (401)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_requires_auth(setup_test_db):
    """PUT returns 401 without authentication."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.put(
            "/api/v1/debug/logging",
            json={"overrides": {"test": "DEBUG"}},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_requires_auth(setup_test_db):
    """GET returns 401 without authentication."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/debug/logging")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Input validation (422)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_invalid_level_returns_422(auth_client):
    """PUT with invalid log level name returns 422."""
    resp = await auth_client.put(
        "/api/v1/debug/logging",
        json={"overrides": {"test.module": "INVALID_LEVEL"}},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_all_valid_levels(auth_client):
    """PUT accepts all valid log level names."""
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        resp = await auth_client.put(
            "/api/v1/debug/logging",
            json={"overrides": {"test.module": level}},
        )
        assert resp.status_code == 200, f"Level {level} should be valid"
        data = resp.json()
        assert data["overrides"].get("test.module") == level
