import pytest
import pytest_asyncio
import io
import uuid
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from src.api.main import app

TEST_DOCS_DIR = Path(__file__).parent.parent / "docs"


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    pass
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"doc_test_{uuid.uuid4().hex[:8]}@example.com"
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
async def test_upload_python_guide(auth_client):
    test_file_path = TEST_DOCS_DIR / "sample_python.txt"
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": ("python_guide.txt", io.BytesIO(content), "text/plain")}
    data = {"strategy_id": "default"}
    
    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    result = response.json()
    
    assert result["title"] == "python_guide.txt"
    assert result["doc_type"] == "txt"
    assert result["status"] == "pending"
    
    return result["id"]


@pytest.mark.asyncio
async def test_upload_openapi_spec(auth_client):
    test_file_path = TEST_DOCS_DIR / "sample_api.yaml"
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": ("api_spec.yaml", io.BytesIO(content), "application/x-yaml")}
    data = {"strategy_id": "semantic"}
    
    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    result = response.json()
    
    assert result["title"] == "api_spec.yaml"
    assert result["doc_type"] == "yaml"
    
    return result["id"]


@pytest.mark.asyncio
async def test_upload_and_wait_for_processing(auth_client):
    test_file_path = TEST_DOCS_DIR / "sample_python.txt"
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": ("test_processing.txt", io.BytesIO(content), "text/plain")}
    data = {"strategy_id": "default"}
    
    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    doc_id = response.json()["id"]
    
    import asyncio
    for _ in range(60):
        await asyncio.sleep(1)
        status_response = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break
    
    final_status = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
    assert final_status.status_code == 200
    result = final_status.json()
    
    assert result["status"] == "completed"
    assert result["chunk_count"] > 0
    
    return doc_id, result["chunk_count"]


@pytest.mark.asyncio
async def test_processed_document_chunks(auth_client):
    test_file_path = TEST_DOCS_DIR / "sample_python.txt"
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": ("chunks_test.txt", io.BytesIO(content), "text/plain")}
    data = {"strategy_id": "default"}
    
    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    doc_id = response.json()["id"]
    
    import asyncio
    for _ in range(60):
        await asyncio.sleep(1)
        status_response = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break
    
    chunks_response = await auth_client.get(f"/api/v1/documents/{doc_id}/chunks")
    assert chunks_response.status_code == 200
    chunks_data = chunks_response.json()
    
    assert chunks_data["total"] > 0
    assert len(chunks_data["chunks"]) > 0
    
    first_chunk = chunks_data["chunks"][0]
    assert "content" in first_chunk
    assert len(first_chunk["content"]) > 0


@pytest.mark.asyncio
async def test_list_documents_with_chunks(auth_client):
    test_file_path = TEST_DOCS_DIR / "sample_python.txt"
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": ("list_test.txt", io.BytesIO(content), "text/plain")}
    data = {"strategy_id": "default"}
    
    await auth_client.post("/api/v1/documents", files=files, data=data)
    
    import asyncio
    await asyncio.sleep(2)
    
    list_response = await auth_client.get("/api/v1/documents")
    assert list_response.status_code == 200
    
    docs = list_response.json()["documents"]
    assert len(docs) >= 1
    
    for doc in docs:
        assert "id" in doc
        assert "title" in doc
        assert "status" in doc
        assert "chunking_strategy" in doc


@pytest.mark.asyncio
async def test_document_processing_status_updates(auth_client):
    test_file_path = TEST_DOCS_DIR / "sample_python.txt"
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": ("status_test.txt", io.BytesIO(content), "text/plain")}
    data = {"strategy_id": "default"}
    
    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    doc_id = response.json()["id"]
    
    status_seen = set()
    
    import asyncio
    for _ in range(60):
        await asyncio.sleep(1)
        status_response = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            status_seen.add(status["status"])
            
            if status["status"] == "completed":
                assert status["processing_step"] == "completed"
                assert status["chunk_count"] > 0
                break
            elif status["status"] == "failed":
                assert status["error_message"] is not None
                break
    
    assert "processing" in status_seen or "completed" in status_seen
