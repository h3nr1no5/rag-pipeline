"""
Test user registration and login persistence using in-process ASGI transport.
Replaces the previous subprocess-based uvicorn server approach.
"""
import pytest
import pytest_asyncio
import uuid
from httpx import AsyncClient, ASGITransport

from src.api.main import app


@pytest_asyncio.fixture(scope="function")
async def registered_user_client():
    """Create a client with a registered and logged-in user."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        email = f"persist_test_{uuid.uuid4().hex[:8]}@example.com"
        password = "TestPass123!"

        signup_resp = await ac.post("/api/v1/auth/signup", json={
            "email": email,
            "password": password,
        })
        assert signup_resp.status_code == 201, f"Signup failed: {signup_resp.text}"

        login_resp = await ac.post("/api/v1/auth/login", json={
            "email": email,
            "password": password,
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json()["access_token"]

        yield email, password, token


@pytest.mark.asyncio
async def test_register_user(registered_user_client):
    """Verify user registration creates a user that can authenticate."""
    _email, _password, token = registered_user_client
    
    assert token is not None
    assert len(token) > 0

    # Verify the token works by accessing a protected endpoint
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers["Authorization"] = f"Bearer {token}"
        response = await ac.get("/api/v1/strategies")
        assert response.status_code == 200, f"Authenticated request failed: {response.text}"


@pytest.mark.asyncio
async def test_login_before_and_after_restart_simulation():
    """
    Verify user credentials persist within a test session.
    A "restart" is simulated by creating a fresh client — the database
    (managed by the autouse setup_test_db fixture) persists within the test.
    """
    email = f"restart_test_{uuid.uuid4().hex[:8]}@example.com"
    password = "RestartTest456!"

    # Signup using one client
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client1:
        signup_resp = await client1.post("/api/v1/auth/signup", json={
            "email": email,
            "password": password,
        })
        assert signup_resp.status_code == 201, f"Signup failed: {signup_resp.text}"

        login_resp = await client1.post("/api/v1/auth/login", json={
            "email": email,
            "password": password,
        })
        assert login_resp.status_code == 200, f"Login before restart failed: {login_resp.text}"
        assert "access_token" in login_resp.json()

    # Simulate restart: create a fresh client (same in-process app, same DB)
    async with AsyncClient(transport=transport, base_url="http://test") as client2:
        # The registered user should still be able to log in
        login_resp2 = await client2.post("/api/v1/auth/login", json={
            "email": email,
            "password": password,
        })
        assert login_resp2.status_code == 200, f"Login after restart failed: {login_resp2.text}"
        assert "access_token" in login_resp2.json()


@pytest.mark.asyncio
async def test_wrong_password_rejected():
    """Verify wrong password returns 401."""
    email = f"wrong_pw_test_{uuid.uuid4().hex[:8]}@example.com"
    password = "CorrectPass789!"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # First register
        await ac.post("/api/v1/auth/signup", json={
            "email": email,
            "password": password,
        })

        # Try wrong password
        login_resp = await ac.post("/api/v1/auth/login", json={
            "email": email,
            "password": "WrongPassword!",
        })
        assert login_resp.status_code == 401, "Wrong password should return 401"


@pytest.mark.asyncio
async def test_multiple_users_independent():
    """Verify multiple users can register and authenticate independently."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        users = []
        for i in range(3):
            email = f"multi_user_{i}_{uuid.uuid4().hex[:8]}@example.com"
            password = f"MultiTest{i}Pass!"

            signup_resp = await ac.post("/api/v1/auth/signup", json={
                "email": email,
                "password": password,
            })
            assert signup_resp.status_code == 201
            users.append((email, password))

        # Each user should be able to log in
        for email, password in users:
            login_resp = await ac.post("/api/v1/auth/login", json={
                "email": email,
                "password": password,
            })
            assert login_resp.status_code == 200, f"Login failed for {email}"
            assert "access_token" in login_resp.json()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
