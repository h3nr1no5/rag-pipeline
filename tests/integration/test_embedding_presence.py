import io
from pathlib import Path

import pytest

TEST_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"



@pytest.mark.asyncio
async def test_embedding_presence_after_processing(auth_client):
    test_text = TEST_DOCS_DIR / "sample_python.txt"
    with open(test_text, "rb") as f:
        content = f.read()

    files = {"file": ("embed_test.txt", io.BytesIO(content), "text/plain")}
    data = {"strategy_id": "recursive"}
    resp = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    import asyncio
    for _ in range(120):
        await asyncio.sleep(1)
        status = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
        if status.status_code == 200 and status.json().get("status") == "completed":
            break

    doc = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert doc.status_code == 200
    assert doc.json().get("embedded") is True

    chunks = await auth_client.get(f"/api/v1/documents/{doc_id}/chunks")
    assert chunks.status_code == 200
    chunks_data = chunks.json()
    if chunks_data.get("chunks"):
        first = chunks_data["chunks"][0]
        emb = first.get("embedding")
        assert emb is None or isinstance(emb, list)
