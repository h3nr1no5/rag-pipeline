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
    for pattern in ["test_clear_embeddings_db_*.sqlite"]:
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
        test_email = f"embeddings_test_{uuid.uuid4().hex[:8]}@example.com"
        signup_response = await ac.post("/api/v1/auth/signup", json={
            "email": test_email,
            "password": "testpassword123"
        })
        login_response = await ac.post("/api/v1/auth/login", json={
            "email": test_email,
            "password": "testpassword123"
        })
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        token = login_response.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


async def upload_and_wait_for_document(client: AsyncClient, filename: str, strategy_id: str = "default", content_type: str = "text/plain") -> str:
    test_file_path = Path(__file__).parent.parent / "docs" / filename
    
    if test_file_path.exists():
        with open(test_file_path, "rb") as f:
            content = f.read()
    else:
        content = b"Sample document content for testing embeddings clear functionality."
    
    files = {"file": (filename, io.BytesIO(content), content_type)}
    data = {"strategy_id": strategy_id}
    
    response = await client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    doc_id = response.json()["id"]
    
    for _ in range(30):
        await asyncio.sleep(1)
        status_response = await client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break
    
    return doc_id


@pytest.mark.asyncio
async def test_clear_embeddings_endpoint_exists(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")
    
    response = await auth_client.post(f"/api/v1/documents/{doc_id}/clear-embeddings")
    assert response.status_code == 200
    result = response.json()
    assert "message" in result
    assert result["chunk_count"] > 0


@pytest.mark.asyncio
async def test_clear_embeddings_clears_vector_data(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")
    
    doc_response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert doc_response.status_code == 200
    doc_data = doc_response.json()
    assert doc_data["embedded"] == True
    
    clear_response = await auth_client.post(f"/api/v1/documents/{doc_id}/clear-embeddings")
    assert clear_response.status_code == 200
    
    doc_response_after = await auth_client.get(f"/api/v1/documents/{doc_id}")
    doc_data_after = doc_response_after.json()
    assert doc_data_after["embedded"] == False


@pytest.mark.asyncio
async def test_reprocess_endpoint_exists(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")
    
    doc_response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert doc_response.status_code == 200
    doc_data = doc_response.json()
    assert doc_data["status"] == "completed"
    
    reprocess_response = await auth_client.post(f"/api/v1/documents/{doc_id}/reprocess")
    assert reprocess_response.status_code == 200
    result = reprocess_response.json()
    assert result["status"] == "pending"
    assert "message" in result


@pytest.mark.asyncio
async def test_clear_embeddings_then_reprocess(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")
    
    doc_response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert doc_response.status_code == 200
    doc_data = doc_response.json()
    original_chunk_count = doc_data["chunk_count"]
    assert doc_data["embedded"] == True
    
    clear_response = await auth_client.post(f"/api/v1/documents/{doc_id}/clear-embeddings")
    assert clear_response.status_code == 200
    clear_result = clear_response.json()
    assert clear_result["chunk_count"] == original_chunk_count
    
    doc_response_after = await auth_client.get(f"/api/v1/documents/{doc_id}")
    doc_data_after = doc_response_after.json()
    assert doc_data_after["embedded"] == False
    assert doc_data_after["status"] == "pending"
    
    reprocess_response = await auth_client.post(f"/api/v1/documents/{doc_id}/reprocess")
    assert reprocess_response.status_code == 200
    reprocess_result = reprocess_response.json()
    assert reprocess_result["status"] == "pending"
    
    for _ in range(30):
        await asyncio.sleep(1)
        status_response = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break
    
    final_doc_response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    final_doc_data = final_doc_response.json()
    assert final_doc_data["chunk_count"] == original_chunk_count


@pytest.mark.asyncio
async def test_clear_embeddings_preserves_chunks(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")
    
    chunks_response = await auth_client.get(f"/api/v1/documents/{doc_id}/chunks")
    assert chunks_response.status_code == 200
    chunks_data_before = chunks_response.json()
    original_chunk_count = chunks_data_before["total"]
    
    clear_response = await auth_client.post(f"/api/v1/documents/{doc_id}/clear-embeddings")
    assert clear_response.status_code == 200
    
    chunks_response_after = await auth_client.get(f"/api/v1/documents/{doc_id}/chunks")
    assert chunks_response_after.status_code == 200
    chunks_data_after = chunks_response_after.json()
    
    assert chunks_data_after["total"] == original_chunk_count
    for chunk in chunks_data_after["chunks"]:
        assert len(chunk["content"]) > 0


@pytest.mark.asyncio
async def test_clear_embeddings_sets_status_correctly(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")
    
    doc_response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert doc_response.status_code == 200
    doc_before = doc_response.json()
    assert doc_before["embedded"] == True
    
    clear_response = await auth_client.post(f"/api/v1/documents/{doc_id}/clear-embeddings")
    assert clear_response.status_code == 200
    
    doc_response_after = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert doc_response_after.status_code == 200
    doc_after = doc_response_after.json()
    assert doc_after["embedded"] == False
    assert doc_after["status"] == "pending"
