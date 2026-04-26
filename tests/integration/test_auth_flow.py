import pytest
import pytest_asyncio
import uuid
from httpx import AsyncClient, ASGITransport
from src.api.main import app


@pytest_asyncio.fixture(scope="function")
async def client(setup_test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(setup_test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        response = await ac.post("/api/v1/auth/signup", json={
            "email": test_email,
            "password": "testpassword123"
        })
        if response.status_code == 400:
            await ac.post("/api/v1/auth/login", json={
                "email": test_email,
                "password": "testpassword123"
            })
        elif response.status_code == 201:
            login_response = await ac.post("/api/v1/auth/login", json={
                "email": test_email,
                "password": "testpassword123"
            })
            token = login_response.json()["access_token"]
            ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_root(client):
    response = await client.get("/api/v1/")
    assert response.status_code == 200
    assert "RAG Pipeline API" in response.json()["service"]


@pytest.mark.asyncio
async def test_signup_and_login(client):
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    
    signup_response = await client.post("/api/v1/auth/signup", json={
        "email": email,
        "password": "testpassword123"
    })
    assert signup_response.status_code == 201
    
    login_response = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "testpassword123"
    })
    assert login_response.status_code == 200
    assert "access_token" in login_response.json()
