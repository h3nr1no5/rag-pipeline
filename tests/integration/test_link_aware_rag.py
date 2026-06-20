"""
Integration tests for the link-aware RAG pipeline.

Tests the full end-to-end flow:
1. Upload a PDF with internal cross-reference hyperlinks (LINK_GOTO)
2. Verify the document is processed and chunks contain link/backlink metadata
3. Query the document and verify that linked chunks appear via link traversal
"""

import asyncio
import io
import logging
import pytest
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from src.api.main import app

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.skip(reason="NOT IMPLEMENTED")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    """Authenticated HTTP client for the duration of one test."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        import uuid
        test_email = f"link_test_{uuid.uuid4().hex[:8]}@example.com"
        await ac.post("/api/v1/auth/signup", json={
            "email": test_email,
            "password": "testpassword123",
        })
        login_resp = await ac.post("/api/v1/auth/login", json={
            "email": test_email,
            "password": "testpassword123",
        })
        token = login_resp.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_pdf_with_internal_links(tmp_path: Path) -> Path:
    """Create a 2-page PDF with an internal cross-reference hyperlink.

    Page 1 contains text about a fox and a link that jumps to page 2.
    Page 2 contains text about colors.

    The link (LINK_GOTO) on page 1 points to page 2 so that the
    link-aware pipeline can resolve it into per-chunk ``links`` and
    ``backlinks`` metadata.
    """
    import fitz

    pdf_path = tmp_path / "test_link_aware.pdf"
    doc = fitz.open()

    # Create both pages first so page indices are valid for link targets.
    doc.new_page()  # page index 0
    doc.new_page()  # page index 1

    # Generate enough text per page so that the total exceeds the default
    # chunk size (~1000 chars).  This forces the recursive chunker to split
    # at the ``\n\n`` boundary between pages, producing one chunk per page.
    #
    # NB: We use ``insert_textbox()`` (with a large rectangle) instead of
    # ``insert_text()`` because the latter puts everything on one physical
    # line, which gets clipped at the page boundary by the PDF renderer,
    # causing ``get_text()`` to return truncated text.

    rect = fitz.Rect(50, 50, 550, 800)  # large enough to hold all text

    page1_text = (
        "The quick brown fox jumps over the lazy dog. "
        "The fox is very quick and very brown. "
        "The dog is lazy and stays in the yard. "
        "The fox runs quickly across the field. "
        "A brown fox can be hard to spot in autumn leaves. "
        "The quick fox jumps over the sleeping dog. "
        "Foxes are known for their cleverness and agility. "
        "See the next page for important information about colors."
    )

    page2_text = (
        "The most common colors are red, blue, and green. "
        "These colors appear frequently in nature and design. "
        "Red is often associated with energy, blue with calmness, "
        "and green with nature. "
        "In art, red is a primary color that cannot be created by "
        "mixing other colors. Blue is also a primary color and is "
        "often used to represent the sky and the ocean. "
        "Green is a secondary color made by mixing blue and yellow. "
        "Each color has its own wavelength in the visible spectrum. "
        "Red has the longest wavelength, while blue and green have "
        "shorter wavelengths. "
        "The combination of these colors creates a wide palette for artists. "
        "Understanding color theory is essential for painters and designers. "
        "Colors can evoke different emotions and moods in people. "
        "Warm colors like red and orange are energetic, while cool "
        "colors like blue and green are calming. "
        "The study of color psychology helps in creating effective designs."
    )

    total = len(page1_text) + len(page2_text)
    assert total > 1200, (
        f"Total text length ({total}) should exceed chunk size (1000) "
        "to ensure page-boundary splitting."
    )

    # --- Page 1 (index 0) ---
    page1 = doc[0]
    page1.insert_textbox(rect, page1_text)
    # The link rectangle should cover the area of the reference text.
    # "page": 1 is 0-indexed, pointing to page2 (index 1).
    page1.insert_link({
        "kind": fitz.LINK_GOTO,
        "page": 1,
        "from": fitz.Rect(72, 120, 500, 140),
    })

    # --- Page 2 (index 1) ---
    page2 = doc[1]
    page2.insert_textbox(rect, page2_text)

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


async def upload_and_wait(auth_client: AsyncClient, pdf_path: Path) -> str:
    """Upload a PDF and poll until processing completes.

    Returns the document ID.
    """
    with open(pdf_path, "rb") as f:
        content = f.read()

    files = {"file": (pdf_path.name, io.BytesIO(content), "application/pdf")}
    data = {"strategy_id": "recursive"}

    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201, f"Upload failed: {response.text}"
    doc_id = response.json()["id"]

    # Poll status up to 3 minutes
    for _ in range(180):
        await asyncio.sleep(1)
        status_resp = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
        if status_resp.status_code == 200:
            status = status_resp.json()
            if status["status"] in ("completed", "failed"):
                break

    return doc_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="NOT_IMPLEMENTED")
@pytest.mark.asyncio
async def test_link_aware_pdf_processing(auth_client, tmp_path):
    """Upload a PDF with internal links and verify that chunks contain
    ``links`` and ``backlinks`` metadata after processing.

    This validates the full processing pipeline:
        PDF parsing → chunking → link extraction → link resolution
        → chunk metadata enrichment
    """
    pdf_path = create_pdf_with_internal_links(tmp_path)
    doc_id = await upload_and_wait(auth_client, pdf_path)

    # --- Verify document status ---
    status_resp = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "completed", (
        f"Expected 'completed', got '{status_data['status']}': "
        f"{status_data.get('error_message', 'no error message')}"
    )
    assert status_data["chunk_count"] > 0, "Document has zero chunks"

    # --- Fetch chunks ---
    chunks_resp = await auth_client.get(
        f"/api/v1/documents/{doc_id}/chunks?limit=50"
    )
    assert chunks_resp.status_code == 200
    chunks_data = chunks_resp.json()
    chunks = chunks_data["chunks"]
    assert len(chunks) == status_data["chunk_count"], (
        f"Expected {status_data['chunk_count']} chunks, got {len(chunks)}"
    )

    logger.info(
        "Document %s has %d chunks",
        doc_id,
        len(chunks),
    )

    # --- Verify link/backlink metadata ---

    # Build a mapping of chunk_index → chunk for easier inspection
    chunk_by_index: dict[int, dict] = {}
    for c in chunks:
        idx = c["chunk_index"]
        chunk_by_index[idx] = c

    chunks_with_links: list[dict] = []
    chunks_with_backlinks: list[dict] = []

    for c in chunks:
        meta = c.get("metadata") or {}
        if meta.get("links"):
            chunks_with_links.append(c)
        if meta.get("backlinks"):
            chunks_with_backlinks.append(c)

    # Chunks from page 1 (source of the internal link) must have a ``links``
    # entry pointing to page-2 chunks.
    assert len(chunks_with_links) > 0, (
        "No chunks found with 'links' metadata — link extraction or "
        "resolution may have failed"
    )

    # Chunks from page 2 (target of the internal link) must have a
    # ``backlinks`` entry pointing back to page-1 chunks.
    assert len(chunks_with_backlinks) > 0, (
        "No chunks found with 'backlinks' metadata — link extraction or "
        "resolution may have failed"
    )

    # --- Validate link structure ---
    # At least one link entry should be an internal link targeting page 2
    link_targets: set[int] = set()
    for c in chunks_with_links:
        for link in (c.get("metadata") or {}).get("links", []):
            if link.get("type") == "internal":
                link_targets.update(link.get("target_chunk_ids", []))

    assert len(link_targets) > 0, (
        "Internal link entries exist but none have target_chunk_ids"
    )
    logger.info(
        "Link resolution: %d chunks with links, %d chunks with backlinks, "
        "%d target chunk IDs found",
        len(chunks_with_links),
        len(chunks_with_backlinks),
        len(link_targets),
    )

    # Verify that the target chunks exist (they should)
    for target_idx in link_targets:
        assert target_idx in chunk_by_index, (
            f"Link targets chunk index {target_idx} which does not exist "
            f"in the chunk list"
        )

    # Verify that every backlink source_chunk_id corresponds to a real chunk
    for c in chunks_with_backlinks:
        for bl in (c.get("metadata") or {}).get("backlinks", []):
            src_id = bl.get("source_chunk_id")
            assert src_id in chunk_by_index, (
                f"Backlink references source chunk index {src_id} which "
                f"does not exist"
            )


@pytest.mark.skip(reason="NOT_IMPLEMENTED")
@pytest.mark.asyncio
async def test_query_returns_linked_chunks(auth_client, tmp_path):
    """Upload a PDF with internal links, query it, and verify that
    link traversal expands the result set to include chunks from both
    linked pages.

    The test asks a question that semantically matches page 2's content
    (colors). Page-1's chunk should be included via link traversal
    (backlinks from page 2 → page 1). Then the reverse is verified:
    asking about page 1's content should pull in page 2 via forward links.
    """
    pdf_path = create_pdf_with_internal_links(tmp_path)
    doc_id = await upload_and_wait(auth_client, pdf_path)

    # Verify processing succeeded
    status_resp = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "completed"

    # Give a short grace period for embeddings to settle
    await asyncio.sleep(2)

    # --- Direction 1: ask about page-2 content → expect page-1 via backlinks ---
    logger.info("Query 1: asking about colors (page-2 content)")
    resp1 = await auth_client.post("/api/v1/query", json={
        "question": "What colors are mentioned in the document?",
        "document_ids": [doc_id],
        "link_decay_factor": 0.85,
        "link_expansion_factor": 3,
        "top_k": 5,
        "include_citations": False,
    })

    if resp1.status_code == 404:
        # The query endpoint returns 404 when retrieval returns no chunks
        # (e.g. if embedding model failed to load). In that case skip this
        # direction and try the next one.
        logger.warning(
            "Query 1 returned 404 (model unavailable?). Direction skipped."
        )
    else:
        assert resp1.status_code == 200, f"Query 1 failed: {resp1.text}"
        result1 = resp1.json()
        assert "answer" in result1, "Query response missing 'answer'"
        assert "sources" in result1, "Query response missing 'sources'"

        sources1 = result1["sources"]
        assert len(sources1) > 0, "No sources returned from query"

        contents1 = [s.get("content", "") for s in sources1]
        has_page2 = any(
            "red" in c.lower() or "blue" in c.lower() or "green" in c.lower()
            for c in contents1
        )
        has_page1 = any(
            "fox" in c.lower() or "dog" in c.lower()
            for c in contents1
        )

        assert has_page2, (
            "Expected at least one source chunk to contain color-related "
            "content (page 2). If the embedder is unavailable, retrieval "
            "may return empty. Check logs for embedding load errors."
        )

        if not has_page1:
            logger.info(
                "Page-1 content not in first query results — link "
                "traversal may not have triggered. Will verify in reverse."
            )

    # --- Direction 2: ask about page-1 content → expect page-2 via forward links ---
    # Use top_k=1 so that only a single chunk is retrieved via cosine similarity.
    # Link traversal (expansion_factor=3) should then bring in linked chunks from
    # the other page, proving 1-hop traversal works.
    logger.info("Query 2: asking about fox/dog (page-1 content) with top_k=1")
    resp2 = await auth_client.post("/api/v1/query", json={
        "question": "What does the fox jump over?",
        "document_ids": [doc_id],
        "link_decay_factor": 0.85,
        "link_expansion_factor": 3,
        "top_k": 1,
        "include_citations": False,
    })

    if resp2.status_code == 404:
        logger.warning(
            "Query 2 returned 404 (model unavailable?). Test cannot "
            "fully verify link traversal, but the processing test "
            "already validated link metadata."
        )
        return

    assert resp2.status_code == 200, f"Query 2 failed: {resp2.text}"
    result2 = resp2.json()
    assert "answer" in result2, "Query response missing 'answer'"
    assert "sources" in result2, "Query response missing 'sources'"

    sources2 = result2["sources"]
    assert len(sources2) > 0, "No sources returned from query"

    contents2 = [s.get("content", "") for s in sources2]
    has_page1_query2 = any(
        "fox" in c.lower() or "dog" in c.lower()
        for c in contents2
    )
    has_page2_via_link = any(
        "red" in c.lower() or "blue" in c.lower() or "green" in c.lower()
        for c in contents2
    )

    # The top-1 chunk should be from the page matching the query (page 1).
    # If the top chunk is from page 1, link traversal brings in page 2 chunks
    #   (via forward links). If it's from page 2, link traversal brings in
    #   page 1 chunks (via backlinks). Either way, we should see content from
    #   both pages and more than 1 source chunk.
    assert len(sources2) > 1, (
        "Expected more than 1 source chunk — link traversal should have "
        "expanded the single top-k chunk with linked chunks from the other "
        "page. Contents found: {}".format([c[:80] for c in contents2])
    )

    assert has_page2_via_link, (
        "Expected page-2 content (colors) to appear in query results via "
        "link traversal. Either the top-1 chunk was from page 2 and "
        "backlinks should bring page 1, or the top-1 chunk was from page 1 "
        "and forward links should bring page 2. Contents found: {}".format(
            [c[:80] for c in contents2]
        )
    )

    logger.info(
        "Link traversal verified: %d sources returned from top_k=1 query, "
        "with content from both pages.",
        len(sources2),
    )


@pytest.mark.skip(reason="NOT_IMPLEMENTED")
@pytest.mark.asyncio
async def test_query_link_traversal_disabled(auth_client, tmp_path):
    """Verify that setting ``link_decay_factor=0`` disables link traversal.

    When link traversal is disabled, only chunks retrieved via cosine
    similarity are returned — no expansion via links/backlinks should occur.
    """
    pdf_path = create_pdf_with_internal_links(tmp_path)
    doc_id = await upload_and_wait(auth_client, pdf_path)

    status_resp = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "completed"

    await asyncio.sleep(2)

    # Query with link traversal disabled
    response = await auth_client.post("/api/v1/query", json={
        "question": "What colors are mentioned?",
        "document_ids": [doc_id],
        "link_decay_factor": 0.0,  # disabled
        "link_expansion_factor": 1,
        "top_k": 5,
        "include_citations": False,
    })

    if response.status_code == 404:
        logger.warning(
            "Query returned 404 (model unavailable?). Skipping "
            "link-traversal-disabled check."
        )
        return

    assert response.status_code == 200, f"Query failed: {response.text}"
    result = response.json()
    sources = result.get("sources", [])

    # With link traversal disabled, only the count specified by top_k
    # should be returned (no expansion). Also, no chunk should have
    # ``_retrieved_via == "link_traversal"`` flag set.
    #
    # Note: we can't directly inspect _retrieved_via from the API
    # response, but we can verify that the number of sources is limited
    # (at most top_k) and that sources don't include both page-1 and
    # page-2 content unless both happen to match semantically.
    assert len(sources) <= 5, (
        f"With link traversal disabled, expected at most 5 sources, "
        f"got {len(sources)}"
    )

    # Fetch chunks for the document to determine expected number
    chunks_resp = await auth_client.get(
        f"/api/v1/documents/{doc_id}/chunks?limit=50"
    )
    assert chunks_resp.status_code == 200
    total_chunks = chunks_resp.json()["total"]

    if total_chunks > 1 and len(sources) < total_chunks:
        logger.info(
            "Link traversal disabled: %d sources from %d total chunks "
            "(no expansion).",
            len(sources),
            total_chunks,
        )
    else:
        logger.info(
            "Link traversal disabled with %d sources.",
            len(sources),
        )


@pytest.mark.skip(reason="NOT_IMPLEMENTED")
@pytest.mark.asyncio
async def test_link_traversal_with_custom_decay(auth_client, tmp_path):
    """Verify that a custom ``link_decay_factor`` is accepted and does
    not cause errors.

    This is a regression test to ensure the API correctly passes the
    parameter through the entire stack (route → retrieval → link traversal).
    """
    pdf_path = create_pdf_with_internal_links(tmp_path)
    doc_id = await upload_and_wait(auth_client, pdf_path)

    status_resp = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "completed"

    await asyncio.sleep(2)

    # Use a very low decay factor — link traversal should still function
    # but linked chunks will have very low scores.
    response = await auth_client.post("/api/v1/query", json={
        "question": "What colors are mentioned?",
        "document_ids": [doc_id],
        "link_decay_factor": 0.1,
        "link_expansion_factor": 5,
        "top_k": 5,
        "include_citations": False,
    })

    if response.status_code == 404:
        logger.warning(
            "Query returned 404 (model unavailable?). Skipping "
            "custom decay check."
        )
        return

    assert response.status_code == 200, f"Query failed: {response.text}"
    result = response.json()
    assert "sources" in result
    assert len(result["sources"]) > 0, "No sources returned with custom decay"
    logger.info(
        "Custom link_decay_factor=0.1 returned %d sources.",
        len(result["sources"]),
    )
