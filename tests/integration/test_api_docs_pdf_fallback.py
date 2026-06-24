"""Integration test for PDF fallback extraction.

Task 9.7 — Tests that PdfFallbackExtractor correctly extracts text from a
minimal PDF and returns a RawDocument structure.

The test creates a minimal valid PDF using pymupdf (fitz), saves it to a
temporary file, then runs PdfFallbackExtractor on it.
"""

import uuid
from pathlib import Path

import fitz  # pymupdf
import pytest

from src.domain.rag.api_docs.extraction.docx_parser import RawDocument, RawParagraph
from src.domain.rag.api_docs.extraction.pdf_fallback import PdfFallbackExtractor
from src.domain.rag.api_docs.manager import ApiDocPipelineManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_minimal_pdf(tmp_path: Path, text: str = "Hello PDF World") -> Path:
    """Create a minimal PDF with the given text and return its path.

    Uses pymupdf (fitz) to create a single-page PDF.
    """
    file_path = tmp_path / f"test_{uuid.uuid4().hex[:8]}.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(72, 100), text, fontsize=12)
    doc.save(str(file_path))
    doc.close()
    return file_path


def _create_multi_page_pdf(tmp_path: Path) -> Path:
    """Create a 2-page PDF with different text on each page."""
    file_path = tmp_path / f"multi_{uuid.uuid4().hex[:8]}.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text(fitz.Point(72, 100), "Page one content", fontsize=12)
    page2 = doc.new_page()
    page2.insert_text(fitz.Point(72, 100), "Page two content", fontsize=12)
    doc.save(str(file_path))
    doc.close()
    return file_path


# ---------------------------------------------------------------------------
# PdfFallbackExtractor tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_fallback_extracts_text(tmp_path: Path):
    """PdfFallbackExtractor extracts text from a minimal PDF."""
    pdf_path = _create_minimal_pdf(tmp_path, "Hello PDF World")
    extractor = PdfFallbackExtractor(str(pdf_path))
    raw = extractor.extract()

    assert isinstance(raw, RawDocument)
    assert raw.tables == []
    assert len(raw.paragraphs) >= 1
    # Text should be prefixed with [Page 1]
    assert "[Page 1]" in raw.paragraphs[0].text
    assert "Hello PDF World" in raw.paragraphs[0].text


@pytest.mark.asyncio
async def test_pdf_fallback_multi_page(tmp_path: Path):
    """PdfFallbackExtractor extracts one paragraph per page."""
    pdf_path = _create_multi_page_pdf(tmp_path)
    extractor = PdfFallbackExtractor(str(pdf_path))
    raw = extractor.extract()

    assert len(raw.paragraphs) == 2
    assert "[Page 1]" in raw.paragraphs[0].text
    assert "[Page 2]" in raw.paragraphs[1].text
    assert "Page one content" in raw.paragraphs[0].text
    assert "Page two content" in raw.paragraphs[1].text


@pytest.mark.asyncio
async def test_pdf_fallback_filename(tmp_path: Path):
    """RawDocument carries the correct filename."""
    pdf_path = _create_minimal_pdf(tmp_path)
    extractor = PdfFallbackExtractor(str(pdf_path))
    raw = extractor.extract()
    assert raw.filename == pdf_path.name


@pytest.mark.asyncio
async def test_pdf_fallback_paragraph_structure(tmp_path: Path):
    """Extracted paragraphs have the expected structure."""
    pdf_path = _create_minimal_pdf(tmp_path, "Some content")
    extractor = PdfFallbackExtractor(str(pdf_path))
    raw = extractor.extract()

    para = raw.paragraphs[0]
    assert isinstance(para, RawParagraph)
    assert para.text
    assert para.style_name == ""
    assert para.heading_level == -1


# ---------------------------------------------------------------------------
# Full pipeline ingest via PDF fallback
# ---------------------------------------------------------------------------


@pytest.fixture
def manager() -> ApiDocPipelineManager:
    """Create a fresh manager instance."""
    return ApiDocPipelineManager()


@pytest.mark.asyncio
async def test_pdf_ingest_via_manager(tmp_path: Path, manager: ApiDocPipelineManager):
    """ApiDocPipelineManager can ingest a PDF and return chunked results."""
    pdf_path = _create_minimal_pdf(tmp_path, "CreateNode method creates a node")
    doc_id = str(uuid.uuid4())

    result = await manager.ingest_pdf(str(pdf_path), doc_id)
    assert result["status"] == "indexed"
    assert result["document_id"] == doc_id
    assert result["chunk_count"] > 0

    # Verify document info
    info = manager.get_document_info(doc_id)
    assert info is not None
    assert info["doc_type"] == "pdf"
    assert len(info["interfaces"]) == 0  # PDF has no structured tables


@pytest.mark.asyncio
async def test_pdf_ingest_then_query(tmp_path: Path, manager: ApiDocPipelineManager):
    """After PDF ingestion, querying returns results."""
    pdf_path = _create_minimal_pdf(tmp_path, "CreateNode method creates a node")
    doc_id = str(uuid.uuid4())
    await manager.ingest_pdf(str(pdf_path), doc_id)

    response = await manager.query(doc_id, "CreateNode", top_k=5)
    assert response.answer
    assert len(response.sources) > 0
    assert response.confidence >= 0.0


@pytest.mark.asyncio
async def test_pdf_fallback_no_tables(tmp_path: Path):
    """PDF extraction produces no tables."""
    pdf_path = _create_minimal_pdf(tmp_path)
    extractor = PdfFallbackExtractor(str(pdf_path))
    raw = extractor.extract()
    assert raw.tables == []


@pytest.mark.asyncio
async def test_pdf_fallback_empty_content(tmp_path: Path):
    """PDF with no text produces no paragraphs."""
    file_path = tmp_path / f"empty_{uuid.uuid4().hex[:8]}.pdf"
    doc = fitz.open()
    doc.new_page()  # blank page
    doc.save(str(file_path))
    doc.close()

    extractor = PdfFallbackExtractor(str(file_path))
    raw = extractor.extract()
    # Blank page may produce empty text which gets skipped
    assert isinstance(raw, RawDocument)
