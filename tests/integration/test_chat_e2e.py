import pytest
import pytest_asyncio
import io
import os
import uuid
import asyncio
import glob
from pathlib import Path
from httpx import AsyncClient, ASGITransport


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    for pattern in ["test_chat_e2e_db_*.sqlite"]:
        for f in glob.glob(f"./data/{pattern}"):
            try:
                os.remove(f)
            except Exception:
                pass
    
    uploads_dir = "./data/uploads"
    if os.path.exists(uploads_dir):
        for f in os.listdir(uploads_dir):
            fpath = os.path.join(uploads_dir, f)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except Exception:
                pass


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    from src.api.main import app
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"chat_test_{uuid.uuid4().hex[:8]}@example.com"
        login_response = await ac.post("/api/v1/auth/login", json={
            "email": test_email,
            "password": "testpassword123"
        })
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        token = login_response.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


async def upload_and_wait_for_document(client: AsyncClient, filename: str, strategy_id: str = "default") -> str:
    test_file_path = Path(__file__).parent.parent / "docs" / filename
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": (filename, io.BytesIO(content), "application/pdf")}
    data = {"strategy_id": strategy_id}
    
    response = await client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201, f"Upload failed: {response.text}"
    doc_id = response.json()["id"]
    
    for _ in range(60):
        await asyncio.sleep(1)
        status_response = await client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break
    
    return doc_id


@pytest.mark.asyncio
async def test_chat_with_ai_short_pdf(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "AI short.pdf")
    
    doc_response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert doc_response.status_code == 200
    doc_data = doc_response.json()
    assert doc_data["status"] == "completed"
    assert doc_data["embedded"] == True
    assert doc_data["chunk_count"] > 0
    
    await asyncio.sleep(2)
    
    response = await auth_client.post("/api/v1/query", json={
        "question": "What is AI?",
        "document_ids": [doc_id]
    })
    
    assert response.status_code == 200
    result = response.json()
    assert "answer" in result
    assert len(result["answer"]) > 0


@pytest.mark.asyncio
async def test_chat_streaming_with_ai_short_pdf(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "AI short.pdf")
    
    await asyncio.sleep(2)
    
    tokens = []
    async with auth_client.stream("POST", "/api/v1/query/stream", json={
        "question": "What are the main topics?",
        "document_ids": [doc_id]
    }) as response:
        assert response.status_code == 200
        
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                import json
                data = json.loads(data_str)
                if "token" in data:
                    tokens.append(data["token"])
                elif "error" in data:
                    pytest.fail(f"Stream error: {data['error']}")
    
    assert len(tokens) > 0, "No tokens received"
    full_response = "".join(tokens)
    assert len(full_response) > 0


@pytest.mark.asyncio
async def test_chat_returns_sources(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "AI short.pdf")
    
    await asyncio.sleep(2)
    
    response = await auth_client.post("/api/v1/query", json={
        "question": "What is discussed?",
        "document_ids": [doc_id]
    })
    
    assert response.status_code == 200
    result = response.json()
    assert "sources" in result
    assert len(result["sources"]) > 0
    
    first_source = result["sources"][0]
    assert "chunk_id" in first_source
    assert "content" in first_source


@pytest.mark.asyncio
async def test_chat_requires_question(auth_client):
    response = await auth_client.post("/api/v1/query", json={
        "question": "",
        "document_ids": ["some-doc-id"]
    })
    
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_requires_documents(auth_client):
    response = await auth_client.post("/api/v1/query", json={
        "question": "Test question",
        "document_ids": []
    })
    
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_chat_with_nonexistent_document(auth_client):
    response = await auth_client.post("/api/v1/query", json={
        "question": "Test question",
        "document_ids": ["00000000-0000-0000-0000-000000000000"]
    })
    
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_unauthorized(auth_client):
    auth_client.headers.pop("Authorization", None)
    
    response = await auth_client.post("/api/v1/query", json={
        "question": "Test",
        "document_ids": ["some-id"]
    })
    
    assert response.status_code in [401, 403]


@pytest.mark.asyncio
async def test_chat_cache_hit(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "AI short.pdf")
    
    await asyncio.sleep(2)
    
    first_response = await auth_client.post("/api/v1/query", json={
        "question": "What is AI?",
        "document_ids": [doc_id]
    })
    assert first_response.status_code == 200
    
    second_response = await auth_client.post("/api/v1/query", json={
        "question": "What is AI?",
        "document_ids": [doc_id]
    })
    assert second_response.status_code == 200
    result = second_response.json()
    
    assert result.get("cached") == True


@pytest.mark.asyncio
async def test_clear_embeddings_and_reprocess(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "AI short.pdf")
    
    doc_response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    doc_data = doc_response.json()
    original_chunk_count = doc_data["chunk_count"]
    
    clear_response = await auth_client.post(f"/api/v1/documents/{doc_id}/clear-embeddings")
    assert clear_response.status_code == 200
    assert clear_response.json()["chunk_count"] == original_chunk_count
    
    doc_response_after = await auth_client.get(f"/api/v1/documents/{doc_id}")
    doc_data_after = doc_response_after.json()
    assert doc_data_after["embedded"] == False
    
    reprocess_response = await auth_client.post(f"/api/v1/documents/{doc_id}/reprocess")
    assert reprocess_response.status_code == 200
    
    for _ in range(60):
        await asyncio.sleep(1)
        status_response = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break
    
    final_doc_response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    final_doc_data = final_doc_response.json()
    assert final_doc_data["chunk_count"] == original_chunk_count
