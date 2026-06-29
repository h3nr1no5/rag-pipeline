"""
Integration test for the cosine (default) RAG backend with verification.

Exercises the default cosine-similarity query pipeline end-to-end to verify
that it returns a substantive answer with properly-scored source chunks.
"""

import io
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.main import app

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    """Authenticated HTTP client with a fresh user per test."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"cosine_verif_{uuid.uuid4().hex[:8]}@example.com"
        await ac.post(
            "/api/v1/auth/signup",
            json={"email": test_email, "password": "testpassword123"},
        )
        login_resp = await ac.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": "testpassword123"},
        )
        token = login_resp.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def upload_and_wait_for_document(
    client: AsyncClient, filename: str
) -> str:
    """Upload a document from ``tests/docs/`` and poll until processing completes."""
    test_docs_dir = __import__("pathlib").Path(__file__).parent.parent / "docs"
    filepath = test_docs_dir / filename

    with open(filepath, "rb") as f:
        content = f.read()

    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    resp = await client.post(
        "/api/v1/documents", files=files, data={"strategy_id": "recursive"}
    )
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    doc_id = resp.json()["id"]

    import asyncio

    for _ in range(60):
        await asyncio.sleep(1)
        status_resp = await client.get(f"/api/v1/documents/{doc_id}/status")
        if status_resp.status_code == 200:
            status = status_resp.json()
            if status["status"] == "completed":
                break
            elif status["status"] == "failed":
                pytest.fail(
                    f"Document {doc_id} processing failed: {status}"
                )

    # Extra settle time for embeddings to be indexed
    import asyncio

    await asyncio.sleep(2)
    return doc_id


def assert_valid_cosine_response(data: dict, min_answer_length: int = 20) -> None:
    """Assert the cosine backend response has the expected structure."""
    assert "answer" in data, "Response missing 'answer' field"
    assert "sources" in data, "Response missing 'sources' field"
    assert len(data["sources"]) > 0, "No sources returned"

    answer = data["answer"]
    assert isinstance(answer, str), f"'answer' is not a string: {type(answer)}"
    assert len(answer) > min_answer_length, (
        f"Answer too short ({len(answer)} chars, expected >{min_answer_length}): "
        f"{answer!r}"
    )

    # Scores should be valid cosine-similarity values in [0, 1]
    for i, src in enumerate(data["sources"]):
        score = src.get("score")
        assert score is not None, f"Source {i} has no 'score'"
        assert isinstance(score, (int, float)), (
            f"Source {i} score is not numeric: {type(score)}"
        )
        assert 0.0 <= score <= 1.0, (
            f"Source {i} score {score:.6f} is outside [0, 1]"
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cosine_backend_substantive_answer(auth_client):
    """
    Upload *sample_python.txt* and query the default cosine backend,
    verifying the answer is substantive and sources have valid scores.
    """
    # Arrange
    doc_id = await upload_and_wait_for_document(
        auth_client, "sample_python.txt"
    )
    question = "What is Python and what are its key features?"

    # Act
    response = await auth_client.post(
        "/api/v1/query",
        json={"question": question, "document_ids": [doc_id]},
    )

    # Assert
    assert (
        response.status_code == 200
    ), f"Cosine endpoint returned {response.status_code}: {response.text}"

    data = response.json()
    assert_valid_cosine_response(data)

    # Print for manual inspection
    print("\n" + "=" * 70)
    print("  COSINE (DEFAULT) BACKEND — VERIFICATION INTEGRATION")
    print("=" * 70)
    print("  Document: sample_python.txt")
    print(f"  Question: {question}")
    print(f"  HTTP Status: {response.status_code}")
    print(f"\n  Answer:\n    {data['answer']}")
    print(f"\n  Sources ({len(data['sources'])}):")
    for i, src in enumerate(data["sources"], 1):
        score = src.get("score", 0)
        content_preview = src.get("content", "")[:120]
        print(f"    [{i}] score={score:.4f}  content={content_preview}...")
    print(f"\n  Latency: {data.get('latency_ms', 'N/A')} ms")
    print(f"  Cached: {data.get('cached', 'N/A')}")
    print("=" * 70)

    # Additional structural checks
    assert "latency_ms" in data, "Response missing 'latency_ms'"
    assert "cached" in data, "Response missing 'cached'"
    assert data.get("latency_ms", 0) >= 0, "Negative latency"


@pytest.mark.asyncio
async def test_cosine_backend_different_questions(auth_client):
    """
    Verify the cosine backend returns relevant answers for two distinct
    questions about the same document, with sensible score variation.
    """
    # Arrange
    doc_id = await upload_and_wait_for_document(
        auth_client, "sample_python.txt"
    )

    questions = [
        "What is Python and what are its key features?",
        "How do you define a function in Python?",
    ]

    for question in questions:
        # Act
        response = await auth_client.post(
            "/api/v1/query",
            json={"question": question, "document_ids": [doc_id]},
        )

        # Assert
        assert (
            response.status_code == 200
        ), f"Failed for question {question!r}: {response.text}"

        data = response.json()
        assert_valid_cosine_response(data)

        print(f"\n  [Q] {question}")
        print(f"  [A] {data['answer'][:150]}...")
        scores = [s.get("score", 0) for s in data["sources"]]
        print(f"  Scores: {[f'{s:.4f}' for s in scores]}")
        assert any(s > 0.0 for s in scores), (
            f"All scores are zero for question: {question}"
        )
