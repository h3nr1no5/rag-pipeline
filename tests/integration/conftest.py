import asyncio
import os
import time
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ["DEBUG_ENDPOINTS_ENABLED"] = "true"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
from src.api.main import app

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def wait_for_document(
    client: AsyncClient,
    document_id: str,
    poll_interval: float = 0.1,
    timeout: float = 30.0,
) -> dict:
    """Poll the document status endpoint until processing completes or fails.

    This is a pure poll-only helper.  It does **not** upload or create
    documents — it only waits for an existing document to finish processing.

    Parameters
    ----------
    client:
        Authenticated HTTP client used to make the status requests.
    document_id:
        ID of the document whose status should be polled.
    poll_interval:
        Seconds to wait between status checks (default 0.1).
    timeout:
        Maximum seconds to keep polling before giving up (default 30.0).

    Returns
    -------
    dict
        The final status JSON body from ``GET /api/v1/documents/{id}/status``
        when the document reaches ``"completed"``.

    Raises
    ------
    pytest.fail(Exception)
        If the document status is ``"failed"`` (includes the error message).
    pytest.fail(Exception)
        If *timeout* expires before the document reaches a terminal state.
    """
    start = time.monotonic()

    while True:
        response = await client.get(f"/api/v1/documents/{document_id}/status")
        if response.status_code == 200:
            status = response.json()
            if status["status"] == "completed":
                # Verify chunk consistency: after "completed" status, all chunks
                # should be committed. If chunk_count doesn't match actual chunks,
                # the background task hasn't finished yet — keep polling.
                doc_resp = await client.get(f"/api/v1/documents/{document_id}")
                if doc_resp.status_code == 200:
                    doc_data = doc_resp.json()
                    stored_count = doc_data.get("chunk_count", 0)

                    chunks_resp = await client.get(
                        f"/api/v1/documents/{document_id}/chunks"
                    )
                    if chunks_resp.status_code == 200:
                        chunks_data = chunks_resp.json()
                        actual_count = len(chunks_data.get("chunks", []))

                        if actual_count > 0 and actual_count == stored_count:
                            return status
                # Fall through to continue polling
            if status["status"] == "failed":
                error_msg = status.get(
                    "error_message", status.get("error", "Unknown error")
                )
                pytest.fail(
                    f"Document {document_id} processing failed: {error_msg}"
                )

        if time.monotonic() - start > timeout:
            pytest.fail(
                f"Document {document_id} did not finish processing "
                f"within {timeout}s"
            )

        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    """Authenticated HTTP client for the duration of a single test.

    Creates a unique user, signs up, logs in, and attaches the returned
    ``Bearer`` token to every subsequent request made through the client.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"int_test_{uuid.uuid4().hex[:8]}@example.com"
        await ac.post(
            "/api/v1/auth/signup",
            json={"email": test_email, "password": "testpassword123"},
        )
        login_response = await ac.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": "testpassword123"},
        )
        token = login_response.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


@pytest.fixture(autouse=True, scope="session")
def seed_singletons():
    """Seed model singletons with test doubles so tests run without real models.

    Sets ``_embedder_instance`` and ``_llm_instance`` before any test runs,
    ensuring ``get_embedder()`` / ``get_llm()`` return immediately.
    """
    import src.domain.services.embedding as emb_mod
    import src.domain.services.llm as llm_mod
    from tests.doubles.embedder import TestEmbedder
    from tests.doubles.llm import TestLLM

    emb_mod._embedder_instance = TestEmbedder()
    emb_mod._embedder_load_time = 0
    llm_mod._llm_instance = TestLLM()


