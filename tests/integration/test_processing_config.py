"""
Integration tests for ProcessingConfig lifecycle:
- ProcessingConfig is created on document upload with strategy defaults
- Custom params (chunk_size, etc.) can override defaults on upload
- Reprocessing creates a new ProcessingConfig (old one is retained)
- PATCH /strategies/{id} updates non-system strategies
- PATCH /strategies/{id} returns 403 for system strategies
"""
import asyncio
import io
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.config import get_settings

TEST_DOCS_DIR = Path(__file__).parent.parent / "docs"


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"pconfig_{uuid.uuid4().hex[:8]}@example.com"
        await ac.post("/api/v1/auth/signup", json={
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


async def upload_and_wait_for_document(
    client: AsyncClient,
    filename: str,
    strategy_id: str = "recursive",
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    separators: str | None = None,
    use_hyperlinks: bool | None = None,
) -> str:
    """Upload a document and wait for it to be processed, returning its ID."""
    test_file_path = TEST_DOCS_DIR / filename
    if not test_file_path.exists():
        # Fallback: create minimal content
        content = b"Sample document content for processing config testing."
        content_type = "text/plain"
        files = {"file": (filename, io.BytesIO(content), content_type)}
    else:
        with open(test_file_path, "rb") as f:
            content = f.read()
        files = {"file": (filename, io.BytesIO(content), "text/plain")}

    data = {"strategy_id": strategy_id}
    if chunk_size is not None:
        data["chunk_size"] = str(chunk_size)
    if chunk_overlap is not None:
        data["chunk_overlap"] = str(chunk_overlap)
    if separators is not None:
        data["separators"] = separators
    if use_hyperlinks is not None:
        data["use_hyperlinks"] = str(use_hyperlinks).lower()

    response = await client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201, f"Upload failed: {response.text}"
    doc_id = response.json()["id"]

    # Wait for processing to complete
    for _ in range(60):
        await asyncio.sleep(1)
        status_response = await client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ("completed", "failed"):
                break

    return doc_id


def _validate_processing_config(config: dict, *, expected_strategy_id: str = "recursive") -> None:
    """Validate required fields and types on a ProcessingConfigResponse dict."""
    assert "id" in config
    assert config["id"] != ""
    assert "document_id" in config
    assert config["document_id"] != ""
    assert config["strategy_id"] == expected_strategy_id
    assert isinstance(config["chunk_size"], int)
    assert config["chunk_size"] >= 50
    assert isinstance(config["chunk_overlap"], int)
    assert config["chunk_overlap"] >= 0
    assert isinstance(config["separators"], list)
    assert len(config["separators"]) > 0
    assert isinstance(config["use_hyperlinks"], bool)
    assert isinstance(config["engine_type"], str)
    assert "created_at" in config


@pytest.mark.asyncio
async def test_upload_creates_processing_config(auth_client):
    """Upload a document and verify a ProcessingConfig record is created
    with the strategy defaults, and that GET /documents/{id} includes
    processing_config with expected fields."""
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")

    # GET /documents/{id} should include processing_config
    response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert response.status_code == 200, f"GET document failed: {response.text}"
    doc = response.json()

    assert "processing_config" in doc
    config = doc["processing_config"]
    assert config is not None, "processing_config should not be None"

    _validate_processing_config(config)

    # Verify the chunk_size matches the strategy default (from settings)
    settings = get_settings()
    assert config["chunk_size"] == settings.default_chunk_size


@pytest.mark.asyncio
async def test_upload_with_override_params(auth_client):
    """Upload with custom chunk_size=200 and verify the processing_config
    reflects the override. Also verify GET /documents/{id}/processing-configs
    returns it."""
    doc_id = await upload_and_wait_for_document(
        auth_client, "sample_python.txt", chunk_size=200, chunk_overlap=20,
    )

    # Check via GET /documents/{id}
    response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert response.status_code == 200
    doc = response.json()
    assert doc["processing_config"] is not None
    assert doc["processing_config"]["chunk_size"] == 200
    assert doc["processing_config"]["chunk_overlap"] == 20

    # Check via GET /documents/{id}/processing-configs
    configs_response = await auth_client.get(f"/api/v1/documents/{doc_id}/processing-configs")
    assert configs_response.status_code == 200
    configs = configs_response.json()
    assert isinstance(configs, list)
    assert len(configs) >= 1

    # The most recent config should have the overridden params
    latest = configs[0]
    assert latest["chunk_size"] == 200
    assert latest["chunk_overlap"] == 20
    assert latest["strategy_id"] == "recursive"


@pytest.mark.asyncio
async def test_reprocess_creates_new_config(auth_client):
    """Create a doc, then reprocess it with different chunk_size=150.
    Verify two ProcessingConfig records exist."""
    doc_id = await upload_and_wait_for_document(auth_client, "sample_python.txt")

    # Reprocess with different chunk_size
    files = {"file": ("dummy.txt", io.BytesIO(b"content"), "text/plain")}
    reprocess_data = {"chunk_size": "150"}
    response = await auth_client.post(
        f"/api/v1/documents/{doc_id}/reprocess",
        files=files,
        data=reprocess_data,
    )
    assert response.status_code == 200, f"Reprocess failed: {response.text}"

    # Wait for reprocessing to complete
    for _ in range(60):
        await asyncio.sleep(1)
        status_response = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ("completed", "failed"):
                break

    # Verify two ProcessingConfig records exist
    configs_response = await auth_client.get(f"/api/v1/documents/{doc_id}/processing-configs")
    assert configs_response.status_code == 200
    configs = configs_response.json()
    assert len(configs) >= 2, f"Expected at least 2 configs, got {len(configs)}"

    # The newest (index 0) should have chunk_size=150, the next should have the default
    settings = get_settings()
    assert configs[0]["chunk_size"] == 150, f"Newest config chunk_size={configs[0]['chunk_size']}"
    assert configs[1]["chunk_size"] == settings.default_chunk_size

    # Both should be valid
    for config in configs:
        _validate_processing_config(config)


@pytest.mark.asyncio
async def test_patch_strategy_updates_strategy(auth_client):
    """Create a non-system strategy via POST /strategies, then PATCH it
    with a new chunk_size, and verify the update via GET /strategies/{id}."""
    # Create a custom strategy
    create_payload = {
        "name": "My Custom Strategy",
        "description": "Custom strategy for testing",
        "chunk_size": 300,
        "chunk_overlap": 30,
        "separators": ["\n\n", "\n", ". "],
        "use_hyperlinks": False,
    }
    create_response = await auth_client.post("/api/v1/strategies", json=create_payload)
    assert create_response.status_code == 201
    created = create_response.json()
    strategy_id = created["id"]

    # PATCH the strategy with a new chunk_size
    patch_payload = {"chunk_size": 450}
    patch_response = await auth_client.patch(
        f"/api/v1/strategies/{strategy_id}", json=patch_payload
    )
    assert patch_response.status_code == 200, f"PATCH failed: {patch_response.text}"
    updated = patch_response.json()
    assert updated["chunk_size"] == 450
    assert updated["id"] == strategy_id
    assert updated["name"] == "My Custom Strategy"

    # Verify via GET /strategies/{id}
    get_response = await auth_client.get(f"/api/v1/strategies/{strategy_id}")
    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched["chunk_size"] == 450


@pytest.mark.asyncio
async def test_patch_system_strategy_returns_403(auth_client):
    """Attempt PATCH on the 'recursive' system strategy and expect 403."""
    patch_payload = {"chunk_size": 999}
    response = await auth_client.patch("/api/v1/strategies/recursive", json=patch_payload)
    assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
    detail = response.json().get("detail", "")
    assert "system" in detail.lower() or "modif" in detail.lower()
