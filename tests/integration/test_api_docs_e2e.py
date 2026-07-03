"""E2E test for the API documentation RAG pipeline via HTTP endpoints.

The background model-warmup task (``warmup_models``) is patched to a no-op
because it loads native MLX/PyTorch models in a background thread, which
causes segfaults in the pytest event-loop environment.  The actual MLX LLM
is still loaded lazily on-demand when the query endpoint runs.
"""

import asyncio
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patches applied at MODULE import time (before any code references them).

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


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FIXTURES_DIR = Path(__file__).parent.parent / "docs"



async def upload_and_wait(client, filename, timeout=120):
    filepath = FIXTURES_DIR / filename
    files = {"file": (filename, io.BytesIO(filepath.read_bytes()), DOCX_MIME)}
    data = {"strategy_id": "api-docs"}
    resp = await client.post("/api/v1/documents", files=files, data=data)
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    doc_id = resp.json()["id"]
    last_status = {}
    for _ in range(timeout):
        await asyncio.sleep(1)
        sr = await client.get(f"/api/v1/documents/{doc_id}/status")
        if sr.status_code == 200:
            s = sr.json()
            last_status = s
            status = s.get("status")
            if status in ("completed", "failed"):
                return doc_id, status, s
    return doc_id, "timeout", last_status


@pytest.mark.asyncio
async def test_upload_docx(auth_client):
    _doc_id, status, data = await upload_and_wait(auth_client, "axis com snippet.docx", timeout=90)
    assert status == "completed", f"Document processing failed: {data}"


@pytest.mark.asyncio
async def test_query_api_docs(auth_client):
    doc_id, status, data = await upload_and_wait(auth_client, "axis com snippet.docx", timeout=90)
    assert status == "completed", f"Document processing failed: {data}"

    resp = await auth_client.post("/api/v1/query/api-docs", json={
        "query": "how to add material?",
        "document_id": doc_id,
    })
    assert resp.status_code == 200, f"Query failed: {resp.text}"
    result = resp.json()
    assert result["answer"], "Answer should not be empty"
    assert result["answer"] != "I don't have enough information to answer this question."
    assert len(result["sources"]) > 0, "Should have sources"
    assert isinstance(result["confidence"], float)
    assert "latency_ms" in result
    assert "reasoning_hint" in result, "Response should include reasoning_hint field"
    assert result["reasoning_hint"] == "", "Fallback path should return empty reasoning_hint"

    resp2 = await auth_client.post("/api/v1/query/api-docs", json={
        "query": "How to add cross section?",
        "document_id": doc_id,
    })
    assert resp2.status_code == 200, f"Second query failed: {resp2.text}"
    result2 = resp2.json()
    assert result2["answer"], "Answer for cross section should not be empty"
    assert result2["answer"] != "I don't have enough information to answer this question."
    assert len(result2["sources"]) > 0, "Should have sources for cross section"
    assert "reasoning_hint" in result2, "Response should include reasoning_hint field"
    assert result2["reasoning_hint"] == "", "Fallback path should return empty reasoning_hint"


@patch(
    "src.domain.services.verification.ResponseVerifier.verify",
    new_callable=AsyncMock,
)
@pytest.mark.asyncio
async def test_query_api_docs_verification_disabled(mock_verify, auth_client):
    """Query with ``verification_enabled=False`` skips the ResponseVerifier.

    Task 7.2: When a client sends ``verification_enabled=false``, the
    ``ResponseVerifier`` should NOT be invoked, and the raw answer should
    be returned.  The ``unsupported_sentences`` field must be empty.
    """
    doc_id, status, data = await upload_and_wait(auth_client, "axis com snippet.docx", timeout=90)
    assert status == "completed", f"Document processing failed: {data}"

    resp = await auth_client.post("/api/v1/query/api-docs", json={
        "query": "how to add material?",
        "document_id": doc_id,
        "verification_enabled": False,
    })
    assert resp.status_code == 200, f"Query failed: {resp.text}"
    result = resp.json()

    # The answer should be present (raw DSPy or fallback output)
    assert result["answer"], "Answer should not be empty"
    assert "latency_ms" in result
    assert isinstance(result["confidence"], float)
    assert len(result["sources"]) > 0, "Should have sources"
    assert "reasoning_hint" in result, "Response should include reasoning_hint field"
    assert result["reasoning_hint"] == "", "Fallback path should return empty reasoning_hint"

    # When verification is disabled, unsupported_sentences must be empty
    assert result.get("unsupported_sentences", None) == [], (
        "Expected empty unsupported_sentences when verification is disabled"
    )

    # The ResponseVerifier should NOT have been called
    mock_verify.assert_not_called()
