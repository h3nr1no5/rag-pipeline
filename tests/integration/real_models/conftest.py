"""Conftest for real-model integration tests.

Overrides *seed_singletons* to a no-op so that real ML model singletons
(LLM, embedder, cross-encoder) are retained for end-to-end profiling tests.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.main import app

# ---------------------------------------------------------------------------
# Fixture overrides
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def seed_singletons():
    """No-op override — keep real ML model singletons for profiling."""
    pass  # pragma: no cover


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    """Authenticated HTTP client with a fresh user per test.

    Creates a unique user, signs up, logs in, and attaches the returned
    ``Bearer`` token to every subsequent request made through the client.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"real_{uuid.uuid4().hex[:8]}@example.com"
        await ac.post(
            "/api/v1/auth/signup",
            json={"email": test_email, "password": "testpassword123"},
        )
        login_resp = await ac.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": "testpassword123"},
        )
        token = login_resp.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac
