"""E2E integration tests for all 4 RAG pipelines with real documents.

Tests the full end-to-end flow for each pipeline:
  - Document upload and background processing
  - Cosine similarity query pipeline  (``POST /api/v1/query``)
  - LangChain hybrid retrieval       (``POST /api/v1/query/langchain``)
  - LlamaIndex retrieval             (``POST /api/v1/query/llamaindex``)
  - API-docs RAG pipeline            (``POST /api/v1/query/api-docs``)

All tests use ``ASGITransport`` for in-process HTTP — no running server needed.
Only model-loading patches are applied (to avoid segfaults from native MLX/PyTorch
threads inside the pytest event-loop environment).
"""

import asyncio
import io
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Module-level patches (applied before any code references the patched symbols)
# ---------------------------------------------------------------------------

# 1. Prevent background model warmup from loading native models in threads.
patch("src.api.main._load_models", new_callable=AsyncMock).start()

# 2. Prevent DSPy configuration from importing MLX (Metal GPU) during the
#    lifespan, which would conflict with PyTorch MPS used by sentence-transformers
#    during document processing and cause a segfault.
patch(
    "src.domain.rag.api_docs.pipeline.lm_adapter.get_mlx_dspy_lm",
    return_value=MagicMock(),
).start()

# 3. Force sentence-transformers to use CPU instead of MPS — PyTorch MPS
#    initialization segfaults inside the pytest event-loop environment.
patch("torch.backends.mps.is_available", return_value=False).start()

os.environ["API_DOCS_DSPY_ENABLED"] = "false"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FIXTURES_DIR = Path(__file__).parent.parent / "docs"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    """Authenticated HTTP client for the duration of a single test.

    Creates a unique user, signs up, logs in, and attaches the returned
    Bearer token to every subsequent request made through the client.
    """
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"rag_pipeline_e2e_{uuid.uuid4().hex[:8]}@example.com"
        resp = await ac.post(
            "/api/v1/auth/signup",
            json={"email": test_email, "password": "testpassword123"},
        )
        assert resp.status_code == 201, f"Signup failed: {resp.text}"

        login_resp = await ac.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": "testpassword123"},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        token = login_resp.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def upload_and_wait_for_document(
    client: AsyncClient,
    filename: str,
    strategy_id: str = "recursive",
    mime_type: str = "application/pdf",
    timeout: int = 60,
) -> str:
    """Upload a document and poll until processing completes.

    Parameters
    ----------
    client:
        Authenticated HTTP client.
    filename:
        Name of the fixture file inside ``tests/docs/``.
    strategy_id:
        Chunking strategy to use (e.g. ``"recursive"``, ``"api-docs"``).
    mime_type:
        MIME type for the uploaded file.
    timeout:
        Maximum seconds to wait for processing to finish.

    Returns
    -------
    str
        The document ID of the successfully processed document.

    Raises
    ------
    AssertionError
        If the upload fails or processing does not reach ``"completed"``.
    """
    filepath = FIXTURES_DIR / filename
    files = {"file": (filename, io.BytesIO(filepath.read_bytes()), mime_type)}
    data = {"strategy_id": strategy_id}

    resp = await client.post("/api/v1/documents", files=files, data=data)
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    doc_id = resp.json()["id"]

    # Poll for completion
    terminal_statuses = {"completed", "failed"}
    for _ in range(timeout):
        await asyncio.sleep(1)
        status_response = await client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status.get("status") in terminal_statuses:
                break

    # Final verification
    final_response = await client.get(f"/api/v1/documents/{doc_id}")
    assert final_response.status_code == 200, "Failed to fetch document after upload"
    doc_data = final_response.json()
    assert doc_data["status"] == "completed", (
        f"Document {doc_id} processing did not complete. "
        f"Status: {doc_data.get('status')}, "
        f"Error: {doc_data.get('error_message', doc_data.get('error', 'N/A'))}"
    )

    return doc_id


# ---------------------------------------------------------------------------
# Task 3.2 — Cosine similarity pipeline
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_cosine_pipeline(auth_client):
    """Cosine similarity RAG pipeline via ``POST /api/v1/query``.

    Uploads a PDF with the ``recursive`` strategy, queries the
    cosine-similarity-based endpoint, and verifies a non-empty answer.
    """
    doc_id = await upload_and_wait_for_document(
        auth_client, "test_pdf.pdf", strategy_id="recursive",
    )

    # Brief settling time for the LLM / embedder singletons
    await asyncio.sleep(2)

    response = await auth_client.post(
        "/api/v1/query",
        json={
            "question": "how to add material?",
            "document_ids": [doc_id],
        },
    )

    assert response.status_code == 200, f"Query failed: {response.text}"
    result = response.json()
    assert "answer" in result, "Response missing 'answer' field"
    assert len(result["answer"]) > 0, "Answer should not be empty"


# ---------------------------------------------------------------------------
# Task 3.3 — LangChain hybrid retrieval pipeline
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_langchain_pipeline(auth_client):
    """LangChain hybrid retrieval pipeline via ``POST /api/v1/query/langchain``.

    Uploads a PDF with the ``recursive`` strategy, queries the
    LangChain (BM25 + FAISS) endpoint, and verifies a non-empty answer.
    """
    doc_id = await upload_and_wait_for_document(
        auth_client, "test_pdf.pdf", strategy_id="recursive",
    )

    await asyncio.sleep(2)

    response = await auth_client.post(
        "/api/v1/query/langchain",
        json={
            "question": "how to add material?",
            "document_ids": [doc_id],
        },
    )

    assert response.status_code == 200, f"Query failed: {response.text}"
    result = response.json()
    assert "answer" in result, "Response missing 'answer' field"
    assert len(result["answer"]) > 0, "Answer should not be empty"


# ---------------------------------------------------------------------------
# Task 3.4 — LlamaIndex retrieval pipeline
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_llamaindex_pipeline(auth_client):
    """LlamaIndex RAG pipeline via ``POST /api/v1/query/llamaindex``.

    Uploads a PDF with the ``recursive`` strategy, queries the
    LlamaIndex-based endpoint, and verifies a non-empty answer.
    """
    doc_id = await upload_and_wait_for_document(
        auth_client, "test_pdf.pdf", strategy_id="recursive",
    )

    await asyncio.sleep(2)

    response = await auth_client.post(
        "/api/v1/query/llamaindex",
        json={
            "question": "how to add material?",
            "document_ids": [doc_id],
        },
    )

    assert response.status_code == 200, f"Query failed: {response.text}"
    result = response.json()
    assert "answer" in result, "Response missing 'answer' field"
    assert len(result["answer"]) > 0, "Answer should not be empty"


# ---------------------------------------------------------------------------
# Task 3.5 — API-docs RAG pipeline
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_api_docs_pipeline(auth_client):
    """API-docs RAG pipeline via ``POST /api/v1/query/api-docs``.

    Uploads a DOCX file with the ``api-docs`` strategy, then queries the
    API-docs query endpoint and verifies a non-empty answer with sources.
    """
    doc_id = await upload_and_wait_for_document(
        auth_client,
        "test docx.docx",
        strategy_id="api-docs",
        mime_type=DOCX_MIME,
    )

    await asyncio.sleep(2)

    response = await auth_client.post(
        "/api/v1/query/api-docs",
        json={
            "query": "how to add material?",
            "document_id": doc_id,
        },
    )

    assert response.status_code == 200, f"Query failed: {response.text}"
    result = response.json()
    assert result["answer"], "Answer should not be empty"
    assert result["answer"] != "I don't have enough information to answer this question.", (
        "Answer is the fallback 'no information' response"
    )
    assert len(result["sources"]) > 0, "Should have sources"
    assert isinstance(result["confidence"], float)
    assert "latency_ms" in result
