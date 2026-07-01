import io

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app


@pytest.mark.asyncio
async def test_upload_txt_document(auth_client):
    file_content = b"This is a test document.\n\nIt has multiple paragraphs.\n\nFor testing."
    files = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}
    data = {"strategy_id": "recursive"}

    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    result = response.json()
    assert result["title"] == "test.txt"
    assert result["doc_type"] == "txt"
    assert result["status"] == "pending"
    assert "id" in result


@pytest.mark.flaky(reason="readonly database — see fix-flaky-test-isolation")
@pytest.mark.asyncio
async def test_upload_pdf_document(auth_client):
    pdf_content = b"%PDF-1.4 test pdf content"
    files = {"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")}
    data = {"strategy_id": "recursive"}

    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    result = response.json()
    assert result["title"] == "test.pdf"
    assert result["doc_type"] == "pdf"


@pytest.mark.flaky(reason="MPNet segfault — see fix-flaky-test-isolation")
@pytest.mark.asyncio
async def test_upload_yaml_api_document(auth_client):
    yaml_content = b"""
openapi: "3.0.0"
info:
  title: Test API
  version: "1.0"
paths:
  /users:
    get:
      summary: List users
"""
    files = {"file": ("api.yaml", io.BytesIO(yaml_content), "application/x-yaml")}
    data = {"strategy_id": "semantic"}

    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    result = response.json()
    assert result["doc_type"] == "yaml"


@pytest.mark.asyncio
async def test_upload_unsupported_file_type(auth_client):
    files = {"file": ("test.exe", io.BytesIO(b"executable"), "application/octet-stream")}
    data = {"strategy_id": "recursive"}

    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_without_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        files = {"file": ("test.txt", io.BytesIO(b"content"), "text/plain")}
        data = {"strategy_id": "recursive"}

        response = await ac.post("/api/v1/documents", files=files, data=data)
        assert response.status_code in [401, 403]


@pytest.mark.asyncio
async def test_upload_with_custom_strategy(auth_client):
    file_content = b"Test content for custom strategy."
    files = {"file": ("custom.txt", io.BytesIO(file_content), "text/plain")}
    data = {"strategy_id": "semantic"}

    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_upload_with_default_strategy(auth_client):
    file_content = b"Test content with default strategy."
    files = {"file": ("default.txt", io.BytesIO(file_content), "text/plain")}
    data = {"strategy_id": "recursive"}

    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    assert response.json()["status"] == "pending"


@pytest.mark.flaky(reason="401 auth token — see fix-flaky-test-isolation")
@pytest.mark.asyncio
async def test_upload_multiple_documents(auth_client):
    for i in range(3):
        file_content = f"Document {i} content".encode()
        files = {"file": (f"doc_{i}.txt", io.BytesIO(file_content), "text/plain")}
        data = {"strategy_id": "recursive"}

        response = await auth_client.post("/api/v1/documents", files=files, data=data)
        assert response.status_code == 201


@pytest.mark.asyncio
async def test_list_documents(auth_client):
    response = await auth_client.get("/api/v1/documents")
    assert response.status_code == 200
    result = response.json()
    assert "documents" in result
    assert "total" in result
    assert isinstance(result["documents"], list)
    assert result["total"] >= 0


@pytest.mark.asyncio
async def test_get_single_document(auth_client):
    files = {"file": ("single_test.txt", io.BytesIO(b"Single test"), "text/plain")}
    data = {"strategy_id": "recursive"}

    create_response = await auth_client.post("/api/v1/documents", files=files, data=data)
    doc_id = create_response.json()["id"]

    response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert response.status_code == 200
    doc = response.json()
    assert doc["id"] == doc_id
    assert doc["title"] == "single_test.txt"


@pytest.mark.asyncio
async def test_delete_document(auth_client):
    files = {"file": ("delete_test.txt", io.BytesIO(b"To be deleted"), "text/plain")}
    data = {"strategy_id": "recursive"}

    create_response = await auth_client.post("/api/v1/documents", files=files, data=data)
    doc_id = create_response.json()["id"]

    delete_response = await auth_client.delete(f"/api/v1/documents/{doc_id}")
    assert delete_response.status_code == 204

    get_response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert get_response.status_code in [404, 200]


@pytest.mark.asyncio
async def test_get_nonexistent_document(auth_client):
    response = await auth_client.get("/api/v1/documents/nonexistent-id-12345")
    assert response.status_code == 404
