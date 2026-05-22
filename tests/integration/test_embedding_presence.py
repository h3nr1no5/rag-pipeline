import pytest
import pytest_asyncio
import io
import uuid
from pathlib import Path
from httpx import AsyncClient, ASGITransport

TEST_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
        test_email = f"embed_test_{uuid.uuid4().hex[:8]}@example.com"
        await ac.post("/api/v1/auth/signup", json={
            "email": test_email,
            "password": "embedpass123"
        })
        login_response = await ac.post("/api/v1/auth/login", json={
            "email": test_email,
            "password": "embedpass123"
        })
        token = login_response.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


@pytest.mark.asyncio
async def test_embedding_presence_after_processing(auth_client):
    test_text = TEST_DOCS_DIR / "sample_python.txt"
    with open(test_text, "rb") as f:
        content = f.read()

    files = {"file": ("embed_test.txt", io.BytesIO(content), "text/plain")}
    data = {"strategy_id": "default"}
    resp = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    import asyncio
    for _ in range(120):
        await asyncio.sleep(1)
        status = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
        if status.status_code == 200 and status.json().get("status") == "completed":
            break

    doc = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert doc.status_code == 200
    assert doc.json().get("embedded") is True

    chunks = await auth_client.get(f"/api/v1/documents/{doc_id}/chunks")
    assert chunks.status_code == 200
    chunks_data = chunks.json()
    if chunks_data.get("chunks"):
        first = chunks_data["chunks"][0]
        emb = first.get("embedding")
        assert emb is None or isinstance(emb, list)
