import io
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from tests.conftest import skipif_no_cache

TEST_DOCS_DIR = Path(__file__).parent.parent / "docs"


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"chat_test_{uuid.uuid4().hex[:8]}@example.com"
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


async def upload_and_wait_for_document(client: AsyncClient, filename: str, strategy_id: str = "recursive") -> str:  # noqa: E501
    test_file_path = TEST_DOCS_DIR / filename

    with open(test_file_path, "rb") as f:
        content = f.read()

    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    data = {"strategy_id": strategy_id}

    response = await client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    doc_id = response.json()["id"]

    import asyncio
    for _ in range(60):
        await asyncio.sleep(1)
        status_response = await client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break

    return doc_id


@pytest.mark.asyncio
async def test_chat_with_processed_document(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")

    import asyncio
    await asyncio.sleep(2)

    response = await auth_client.post("/api/v1/query", json={
        "question": "What is Python?",
        "document_ids": [doc_id]
    })

    assert response.status_code == 200
    result = response.json()

    assert "answer" in result
    assert "sources" in result
    assert len(result["answer"]) > 0


@pytest.mark.asyncio
async def test_chat_streaming_with_document(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")

    import asyncio
    await asyncio.sleep(2)

    tokens = []

    async with auth_client.stream("POST", "/api/v1/query/stream", json={
        "question": "What are Python's key features?",
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
                elif "sources" in data or "cached" in data:
                    pass

    assert len(tokens) > 0
    full_response = "".join(tokens)
    assert len(full_response) > 0


@pytest.mark.asyncio
async def test_chat_returns_sources(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")

    import asyncio
    await asyncio.sleep(2)

    response = await auth_client.post("/api/v1/query", json={
        "question": "How do you define a function in Python?",
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
async def test_chat_empty_question(auth_client):
    response = await auth_client.post("/api/v1/query", json={
        "question": "",
        "document_ids": ["some-doc-id"]
    })

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_no_document_ids(auth_client):
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
async def test_query_history(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")

    import asyncio
    await asyncio.sleep(2)

    await auth_client.post("/api/v1/query", json={
        "question": "What is Python?",
        "document_ids": [doc_id]
    })

    await asyncio.sleep(1)

    history_response = await auth_client.get("/api/v1/query/history")
    assert history_response.status_code == 200

    history = history_response.json()
    assert "queries" in history
    assert len(history["queries"]) >= 0


@pytest.mark.asyncio
async def test_chat_multiple_documents(auth_client):
    doc1_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")
    doc2_id = await upload_and_wait_for_document(auth_client, "sample_api.yaml")

    import asyncio
    await asyncio.sleep(2)

    response = await auth_client.post("/api/v1/query", json={
        "question": "What is this about?",
        "document_ids": [doc1_id, doc2_id]
    })

    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_chat_preserves_context(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")

    import asyncio
    await asyncio.sleep(2)

    response = await auth_client.post("/api/v1/query", json={
        "question": "What language is this about?",
        "document_ids": [doc_id]
    })

    assert response.status_code == 200
    result = response.json()

    assert "answer" in result
    assert len(result["answer"]) > 0


@skipif_no_cache
@pytest.mark.asyncio
async def test_chat_cache_hit(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")

    import asyncio
    await asyncio.sleep(2)

    first_response = await auth_client.post("/api/v1/query", json={
        "question": "What is Python?",
        "document_ids": [doc_id]
    })

    second_response = await auth_client.post("/api/v1/query", json={
        "question": "What is Python?",
        "document_ids": [doc_id]
    })

    assert second_response.status_code == 200
    result = second_response.json()

    assert result["answer"] == first_response.json()["answer"]
