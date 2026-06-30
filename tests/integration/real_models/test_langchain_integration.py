"""Real-model integration test for the LangChain pipeline with profiling.

Uploads a real PDF with semantic chunking, exercises
``LangChainQAChain.generate()`` with real ML models, asserts on
``[PROFILE]`` log output to confirm all five StepTimer probes fire,
and validates the answer content.
"""

import asyncio
import io
import logging
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    """Authenticated HTTP client with a fresh user per test."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"lc_profile_{uuid.uuid4().hex[:8]}@example.com"
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


async def upload_and_wait(auth_client, filename: str, timeout: int = 300) -> str:
    """Upload a document and poll until processing is complete.

    Parameters
    ----------
    auth_client:
        Authenticated HTTP client.
    filename:
        Name of a file in ``tests/docs/`` (e.g. ``"test_pdf.pdf"``).
    timeout:
        Maximum number of seconds to wait for processing to complete.

    Returns
    -------
    str
        The uploaded document's ID.
    """
    test_docs_dir = Path(__file__).parent.parent.parent / "docs"
    filepath = test_docs_dir / filename

    with open(filepath, "rb") as f:
        content = f.read()

    files = {"file": (filename, io.BytesIO(content), "application/pdf")}
    resp = await auth_client.post(
        "/api/v1/documents", files=files, data={"strategy_id": "semantic"}
    )
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    doc_id = resp.json()["id"]

    for _ in range(timeout):
        await asyncio.sleep(1)
        status_resp = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
        if status_resp.status_code == 200:
            status = status_resp.json()
            if status["status"] == "completed":
                break
            elif status["status"] == "failed":
                pytest.fail(
                    f"Document {doc_id} processing failed: {status}"
                )

    # Extra settle time for embeddings to be indexed
    await asyncio.sleep(2)
    return doc_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_langchain_profile_lines(auth_client, caplog):
    """Upload ``test_pdf.pdf`` (semantic chunking), query the LangChain
    pipeline, verify all five ``[PROFILE]`` log lines are emitted, and
    assert the answer contains ``"material"``.

    Expected probe names
    --------------------
    ``retrieve``, ``build_prompt``, ``llm_generate``, ``verify``,
    ``clean_response``
    """
    caplog.set_level(logging.INFO)

    # Arrange
    doc_id = await upload_and_wait(auth_client, "test_pdf.pdf")

    # Act
    response = await auth_client.post(
        "/api/v1/query/langchain",
        json={"question": "how to add material from catalog?", "document_ids": [doc_id]},
    )
    assert response.status_code == 200, f"Query failed: {response.text}"

    # Collect [PROFILE] lines from caplog
    profile_lines = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO
        and isinstance(r.getMessage(), str)
        and r.getMessage().startswith("[PROFILE]")
    ]

    expected_steps = [
        "retrieve",
        "build_prompt",
        "llm_generate",
        "verify",
        "clean_response",
    ]
    profile_texts = [r.getMessage() for r in profile_lines]

    print("\n=== LangChain PROFILE lines ===")
    for line in profile_texts:
        print(f"  {line}")

    # Assert each expected step appears in at least one [PROFILE] line
    for step in expected_steps:
        assert any(step in t for t in profile_texts), (
            f"Missing [PROFILE] line for step '{step}'. "
            f"Found: {profile_texts}"
        )

    # Assert answer content
    result = response.json()
    assert "answer" in result, "Response missing 'answer' field"
    assert "material" in result["answer"].lower(), (
        f"Answer should contain 'material', got: {result['answer'][:200]}"
    )
