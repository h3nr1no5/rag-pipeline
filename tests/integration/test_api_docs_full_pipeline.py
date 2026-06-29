"""Integration test for the full API documentation pipeline.

Task 9.6 — Tests end-to-end: create synthetic DOCX → ingest via
ApiDocPipelineManager → query and verify results.

Requires the async database fixture (autouse setup_test_db).
"""

import uuid
from pathlib import Path

import pytest
from docx import Document

from src.domain.rag.api_docs.manager import ApiDocPipelineManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_synthetic_docx(tmp_path: Path) -> Path:
    """Create a synthetic DOCX with a method table and save it to disk."""
    doc = Document()
    doc.add_heading("Test API", level=1)
    doc.add_heading("INode Interface", level=2)
    doc.add_paragraph("Node interface for testing.")

    # Method table
    table = doc.add_table(rows=2, cols=4)
    headers = ["Method", "Parameters", "Return Type", "Description"]
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h
    table.rows[1].cells[0].text = "Create"
    table.rows[1].cells[1].text = "x: double\ny: double"
    table.rows[1].cells[2].text = "void"
    table.rows[1].cells[3].text = "Creates a node"

    # Property table
    table2 = doc.add_table(rows=2, cols=4)
    headers2 = ["Name", "Type", "Access", "Description"]
    for i, h in enumerate(headers2):
        table2.rows[0].cells[i].text = h
    table2.rows[1].cells[0].text = "Count"
    table2.rows[1].cells[1].text = "int"
    table2.rows[1].cells[2].text = "read"
    table2.rows[1].cells[3].text = "Number of children"

    file_path = tmp_path / f"synthetic_{uuid.uuid4().hex[:8]}.docx"
    doc.save(str(file_path))
    return file_path


@pytest.fixture
def manager() -> ApiDocPipelineManager:
    """Create a fresh manager instance for each test."""
    return ApiDocPipelineManager()


@pytest.fixture
def docx_path(tmp_path: Path) -> Path:
    """Create a synthetic DOCX and return its path."""
    return _create_synthetic_docx(tmp_path)


# ---------------------------------------------------------------------------
# Full pipeline test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_ingest_and_query(manager: ApiDocPipelineManager, docx_path: Path):
    """The full pipeline runs end-to-end without errors."""
    doc_id = str(uuid.uuid4())

    # Ingest
    ingest_result = await manager.ingest_docx(str(docx_path), doc_id)
    assert ingest_result["status"] == "indexed"
    assert ingest_result["document_id"] == doc_id
    assert ingest_result["chunk_count"] > 0
    assert isinstance(ingest_result["interface_count"], int)

    # Verify indexed
    assert manager.is_indexed(doc_id)
    assert doc_id in manager.get_indexed_docs()


@pytest.mark.asyncio
async def test_full_pipeline_query_returns_results(manager: ApiDocPipelineManager, docx_path: Path):
    """After ingestion, querying returns sources and answer."""
    doc_id = str(uuid.uuid4())
    await manager.ingest_docx(str(docx_path), doc_id)

    # Query
    response = await manager.query(doc_id, "How do I create a node?", top_k=5)
    assert response.answer
    assert len(response.sources) > 0
    assert response.confidence >= 0.0
    assert response.latency_ms >= 0

    # At least one source should reference the Create function or INode
    source = response.sources[0]
    assert source.chunk_id
    assert source.content


@pytest.mark.asyncio
async def test_full_pipeline_query_not_indexed_raises(manager: ApiDocPipelineManager):
    """Querying a non-existent document raises ValueError."""
    with pytest.raises(ValueError, match="has not been indexed"):
        await manager.query("nonexistent-id", "test query")


@pytest.mark.asyncio
async def test_full_pipeline_document_lifecycle(manager: ApiDocPipelineManager, docx_path: Path):
    """Documents can be added, queried, removed, and checked."""
    doc_id = str(uuid.uuid4())
    assert not manager.is_indexed(doc_id)

    await manager.ingest_docx(str(docx_path), doc_id)
    assert manager.is_indexed(doc_id)

    info = manager.get_document_info(doc_id)
    assert info is not None
    assert info["doc_type"] == "docx"
    assert len(info["interfaces"]) > 0

    manager.remove_document(doc_id)
    assert not manager.is_indexed(doc_id)
    assert manager.get_document_info(doc_id) is None
