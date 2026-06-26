import io
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_test_doc = "AI short.pdf"


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"pdf_test_{uuid.uuid4().hex[:8]}@example.com"
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


async def upload_and_wait_for_document(client: AsyncClient, filename: str, strategy_id: str = "recursive") -> str:
    test_file_path = Path(__file__).parent.parent / "docs" / filename

    with open(test_file_path, "rb") as f:
        content = f.read()

    files = {"file": (filename, io.BytesIO(content), "application/pdf")}
    data = {"strategy_id": strategy_id}

    response = await client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    doc_id = response.json()["id"]

    import asyncio
    for _ in range(180):
        await asyncio.sleep(1)
        status_response = await client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break

    return doc_id


@pytest.mark.asyncio
async def test_upload_test_doc(auth_client):
    test_file_path = Path(__file__).parent.parent / "docs" / _test_doc

    with open(test_file_path, "rb") as f:
        content = f.read()

    files = {"file": ("AI short.pdf", io.BytesIO(content), "application/pdf")}
    data = {"strategy_id": "recursive"}

    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    result = response.json()

    assert result["title"] == "AI short.pdf"
    assert result["doc_type"] == "pdf"
    assert result["status"] == "pending"

    return result["id"]


@pytest.mark.asyncio
async def test_upload_and_process_test_doc(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, _test_doc)

    status_response = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
    assert status_response.status_code == 200
    status = status_response.json()

    if status["status"] == "processing":
        import asyncio
        for _ in range(60):
            await asyncio.sleep(1)
            status_response = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break

    assert status["status"] == "completed", f"Document status is {status['status']}: {status.get('error_message', '')}"
    assert status["chunk_count"] > 0

    return doc_id, status["chunk_count"]


@pytest.mark.asyncio
async def test_chunks_endpoint_exists(auth_client):

    test_file_path = Path(__file__).parent.parent / "docs" / _test_doc

    with open(test_file_path, "rb") as f:
        content = f.read()

    files = {"file": ("test_chunks.pdf", io.BytesIO(content), "application/pdf")}
    data = {"strategy_id": "recursive"}

    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    doc_id = response.json()["id"]

    chunks_response = await auth_client.get(f"/api/v1/documents/{doc_id}/chunks")
    assert chunks_response.status_code == 200


@pytest.mark.asyncio
async def test_chat_with_test_doc(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, _test_doc)

    import asyncio
    await asyncio.sleep(2)

    response = await auth_client.post("/api/v1/query", json={
        "question": "How to use AI?",
        "document_ids": [doc_id]
    })

    assert response.status_code == 200
    result = response.json()

    assert "answer" in result
    assert "sources" in result


@pytest.mark.asyncio
async def test_chat_streaming_with_test_doc(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, _test_doc)

    import asyncio
    await asyncio.sleep(2)

    tokens = []

    async with auth_client.stream("POST", "/api/v1/query/stream", json={
        "question": "What is AI?",
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

    assert len(tokens) > 0
    full_response = "".join(tokens)
    assert len(full_response) > 0
