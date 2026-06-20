import pytest
import pytest_asyncio
import io
import uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from src.api.main import app
from src.infrastructure.database.models import Document


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    """Authenticated HTTP client for document-related tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"doc_progress_{uuid.uuid4().hex[:8]}@example.com"
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


@pytest_asyncio.fixture(scope="function")
async def db_session(setup_test_db):
    """Provide a SQLAlchemy async session connected to the test database.

    The import is done **inside** the fixture so that it picks up the patched
    ``async_session_maker`` after ``setup_test_db`` has run.
    """
    from src.infrastructure.database.session import async_session_maker as sm

    async with sm() as session:
        yield session


# ── Helpers ────────────────────────────────────────────────────────────

_PROGRESS_FIELDS = ("parsing_progress", "chunking_progress", "saving_progress", "saved_chunks")


def _assert_progress_fields(body: dict, *, check_zero_saved_chunks: bool = True) -> None:
    """Assert that *body* contains all required per-stage progress fields
    and that they are integers.

    Works for both the status endpoint response (which has ``stage_detail``)
    and the document-response schema (which does **not** include
    ``stage_detail``).
    """
    for field in _PROGRESS_FIELDS:
        assert field in body, f"Missing field: {field}"
        assert isinstance(body[field], int), f"{field} should be int, got {type(body[field])}"
    if "stage_detail" in body:
        assert isinstance(body["stage_detail"], str)
    if check_zero_saved_chunks:
        assert body["saved_chunks"] == 0


# ── Task 7.2: Status endpoint ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_endpoint_returns_all_progress_fields(auth_client) -> None:
    """GET /documents/{id}/status returns parsing_progress, chunking_progress,
    saving_progress, saved_chunks, and stage_detail."""
    files = {"file": ("status_test.txt", io.BytesIO(b"Content for progress test."), "text/plain")}
    data = {"strategy_id": "recursive"}
    upload_resp = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    status_resp = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
    assert status_resp.status_code == 200
    _assert_progress_fields(status_resp.json())


@pytest.mark.asyncio
async def test_status_endpoint_pending_doc_has_zero_saved_chunks(auth_client) -> None:
    """For a freshly uploaded document saved_chunks starts at 0."""
    files = {"file": ("pending_test.txt", io.BytesIO(b"Fresh upload."), "text/plain")}
    data = {"strategy_id": "recursive"}
    upload_resp = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    status_resp = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
    assert status_resp.status_code == 200
    _assert_progress_fields(status_resp.json(), check_zero_saved_chunks=True)


# ── Task 7.3: List endpoint ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_endpoint_returns_progress_fields(auth_client) -> None:
    """Every document in the list response includes per-stage progress fields (as
    integers, with saved_chunks starting at 0)."""
    for i in range(2):
        content = f"List test doc {i}.".encode()
        files = {"file": (f"list_{i}.txt", io.BytesIO(content), "text/plain")}
        data = {"strategy_id": "recursive"}
        resp = await auth_client.post("/api/v1/documents", files=files, data=data)
        assert resp.status_code == 201

    list_resp = await auth_client.get("/api/v1/documents")
    assert list_resp.status_code == 200
    body = list_resp.json()

    assert body["total"] >= 2

    for doc in body["documents"]:
        _assert_progress_fields(doc, check_zero_saved_chunks=True)


# ── Task 7.4: Reprocess resets saved_chunks ───────────────────────────


@pytest.mark.asyncio
async def test_reprocess_resets_saved_chunks(auth_client, db_session) -> None:
    """Calling POST /documents/{id}/reprocess resets saved_chunks back to 0."""
    # Upload
    files = {"file": ("repro_test.txt", io.BytesIO(b"Reprocess target."), "text/plain")}
    data = {"strategy_id": "recursive"}
    upload_resp = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    # Simulate a partially-processed document by directly writing to the DB
    result = await db_session.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    assert doc is not None
    doc.saved_chunks = 5
    await db_session.commit()

    # Reprocess
    repro_resp = await auth_client.post(f"/api/v1/documents/{doc_id}/reprocess")
    assert repro_resp.status_code == 200

    # Verify saved_chunks was reset to 0
    status_resp = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["saved_chunks"] == 0


@pytest.mark.asyncio
async def test_reprocess_response_indicates_pending(auth_client, db_session) -> None:
    """The reprocess endpoint response itself reports status='pending'."""
    files = {"file": ("repro_resp.txt", io.BytesIO(b"Check reprocess response."), "text/plain")}
    data = {"strategy_id": "recursive"}
    upload_resp = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    # Manipulate so the document looks partially processed
    result = await db_session.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    assert doc is not None
    doc.status = "processing"
    doc.processing_step = "saving"
    doc.saved_chunks = 3
    await db_session.commit()

    # The reprocess response itself should say "pending"
    repro_resp = await auth_client.post(f"/api/v1/documents/{doc_id}/reprocess")
    assert repro_resp.status_code == 200
    assert repro_resp.json()["status"] == "pending"
    assert "message" in repro_resp.json()
