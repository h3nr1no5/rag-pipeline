import pytest
import pytest_asyncio
import uuid
from httpx import AsyncClient, ASGITransport
from src.api.main import app


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"strategy_test_{uuid.uuid4().hex[:8]}@example.com"
        await ac.post("/api/v1/auth/signup", json={
            "email": test_email,
            "password": "testpassword123"
        })
        login_response = await ac.post("/api/v1/auth/login", json={
            "email": test_email,
            "password": "testpassword123"
        })
        token = login_response.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


@pytest.mark.asyncio
async def test_list_strategies(auth_client):
    response = await auth_client.get("/api/v1/strategies")
    assert response.status_code == 200
    strategies = response.json()
    assert isinstance(strategies, list)
    assert len(strategies) >= 2
    strategy_names = [s["name"] for s in strategies]
    assert "Recursive" in strategy_names
    assert "Semantic Chunking" in strategy_names


@pytest.mark.asyncio
async def test_get_strategy_by_id(auth_client):
    response = await auth_client.get("/api/v1/strategies/recursive")
    assert response.status_code == 200
    strategy = response.json()
    assert strategy["id"] == "recursive"
    assert strategy["name"] == "Recursive"
    assert "chunk_size" in strategy
    assert "chunk_overlap" in strategy
    assert "separators" in strategy


@pytest.mark.asyncio
async def test_get_nonexistent_strategy(auth_client):
    response = await auth_client.get("/api/v1/strategies/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_custom_strategy(auth_client):
    custom_strategy = {
        "name": "Custom Strategy",
        "description": "For testing",
        "chunk_size": 300,
        "chunk_overlap": 50,
        "separators": ["\n\n", "\n", ". "],
        "use_hyperlinks": False
    }
    response = await auth_client.post("/api/v1/strategies", json=custom_strategy)
    assert response.status_code == 201
    strategy = response.json()
    assert strategy["name"] == "Custom Strategy"
    assert strategy["chunk_size"] == 300
    assert strategy["id"] is not None


@pytest.mark.asyncio
async def test_strategy_validation(auth_client):
    invalid_strategy = {
        "name": "",
        "chunk_size": -100,
        "chunk_overlap": 1000,
    }
    response = await auth_client.post("/api/v1/strategies", json=invalid_strategy)
    assert response.status_code == 422
