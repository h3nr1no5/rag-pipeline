import io
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.main import app


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"query_test_{uuid.uuid4().hex[:8]}@example.com"
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


async def create_test_document(client: AsyncClient, title: str, content: str) -> str:
    files = {"file": (title, io.BytesIO(content.encode()), "text/plain")}
    data = {"strategy_id": "recursive"}
    response = await client.post("/api/v1/documents", files=files, data=data)
    return response.json()["id"]


@pytest.mark.asyncio
async def test_query_requires_document_ids(auth_client):
    response = await auth_client.post("/api/v1/query", json={
        "question": "What is this about?",
        "document_ids": []
    })
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_query_with_nonexistent_document(auth_client):
    response = await auth_client.post("/api/v1/query", json={
        "question": "Test question",
        "document_ids": ["nonexistent-doc-id"]
    })
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_query_with_invalid_document_format(auth_client):
    response = await auth_client.post("/api/v1/query", json={
        "question": "Test question",
        "document_ids": ["not-a-valid-uuid-format"]
    })
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_query_without_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/v1/query", json={
            "question": "Test?",
            "document_ids": ["some-doc-id"]
        })
        assert response.status_code in [401, 403]


@pytest.mark.asyncio
async def test_query_streaming_endpoint(auth_client):
    doc_id = await create_test_document(auth_client, "stream_test.txt", "Content for streaming test.")

    async with auth_client.stream("POST", "/api/v1/query/stream", json={
        "question": "What is this about?",
        "document_ids": [doc_id]
    }) as response:
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_query_streaming_requires_documents(auth_client):
    async with auth_client.stream("POST", "/api/v1/query/stream", json={
        "question": "What is this?",
        "document_ids": []
    }) as response:
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_selected_documents(auth_client):
    await create_test_document(auth_client, "doc1.txt", "First doc")
    await create_test_document(auth_client, "doc2.txt", "Second doc")

    response = await auth_client.get("/api/v1/documents")
    assert response.status_code == 200
    docs = response.json()["documents"]

    assert len(docs) >= 2
    doc_titles = [d["title"] for d in docs]
    assert "doc1.txt" in doc_titles
    assert "doc2.txt" in doc_titles


@pytest.mark.asyncio
async def test_document_selection_filter_by_status(auth_client):
    await create_test_document(auth_client, "pending.txt", "Pending content")

    response = await auth_client.get("/api/v1/documents")
    assert response.status_code == 200
    docs = response.json()["documents"]

    for doc in docs:
        assert "status" in doc
        assert doc["status"] in ["pending", "processing", "completed", "failed"]


@pytest.mark.asyncio
async def test_document_selection_filter_by_type(auth_client):
    await create_test_document(auth_client, "text.txt", "Text content")

    response = await auth_client.get("/api/v1/documents")
    assert response.status_code == 200
    docs = response.json()["documents"]

    text_docs = [d for d in docs if d.get("doc_type") == "txt"]
    assert len(text_docs) >= 1
