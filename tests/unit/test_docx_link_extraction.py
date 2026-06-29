"""Unit tests for DocxParser.extract_links().

Uses mocking to avoid requiring real .docx files with hyperlinks.
Tests cover:
- DOCX with no hyperlinks returns empty list
- Hyperlinks via paragraph.hyperlinks (primary path)
- Hyperlinks via run.hyperlink (fallback path)
- Malformed hyperlink (rel_id missing from rels) skipped with warning
- Non-existent file propagates error
- Multiple paragraphs with multiple links
- Fallback from rel_id to rId attribute
"""

from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.parsers.base import DocxParser


@pytest.fixture
def parser() -> DocxParser:
    """Fixture providing a DocxParser instance."""
    return DocxParser()


def _make_doc_mock():
    """Create a base mock Document with paragraph list and part.rels dict."""
    doc_mock = MagicMock()
    doc_mock.paragraphs = []
    doc_mock.part.rels = {}
    return doc_mock


def _make_paragraph_mock(hyperlinks=None, runs=None):
    """Create a mock paragraph with the given hyperlinks and runs."""
    para = MagicMock()
    para.hyperlinks = hyperlinks
    para.runs = runs or []
    return para


def _make_hyperlink_mock(rel_id="rId1"):
    """Create a mock hyperlink with rel_id set; rId is left as None."""
    hl = MagicMock()
    hl.rel_id = rel_id
    hl.rId = None
    return hl


# ---------------------------------------------------------------------------
# 1 — No links
# ---------------------------------------------------------------------------


@patch("docx.Document")
@pytest.mark.asyncio
async def test_extract_no_links(mock_document, parser):
    """DOCX with no hyperlinks should return an empty list."""
    doc_mock = _make_doc_mock()
    para = _make_paragraph_mock(hyperlinks=None, runs=[])
    doc_mock.paragraphs = [para]
    mock_document.return_value = doc_mock

    result = await parser.extract_links("fake.docx")

    assert result == []
    mock_document.assert_called_once_with("fake.docx")


# ---------------------------------------------------------------------------
# 2 — Paragraph hyperlinks (primary path)
# ---------------------------------------------------------------------------


@patch("docx.Document")
@pytest.mark.asyncio
async def test_extract_external_links_via_paragraph_hyperlinks(mock_document, parser):
    """Hyperlinks attached to paragraph.hyperlinks should be extracted."""
    doc_mock = _make_doc_mock()
    hl = _make_hyperlink_mock(rel_id="rId1")
    doc_mock.part.rels["rId1"] = MagicMock(target_ref="https://example.com")
    para = _make_paragraph_mock(hyperlinks=[hl], runs=[])
    doc_mock.paragraphs = [para]
    mock_document.return_value = doc_mock

    result = await parser.extract_links("fake.docx")

    assert len(result) == 1
    assert result[0].type == "external"
    assert result[0].uri == "https://example.com"


# ---------------------------------------------------------------------------
# 3 — Run hyperlink (fallback path)
# ---------------------------------------------------------------------------


@patch("docx.Document")
@pytest.mark.asyncio
async def test_extract_external_links_via_run_hyperlink(mock_document, parser):
    """Hyperlinks via run.hyperlink (fallback) should be extracted."""
    doc_mock = _make_doc_mock()
    hl = _make_hyperlink_mock(rel_id="rId1")
    doc_mock.part.rels["rId1"] = MagicMock(target_ref="https://fallback.example.com")

    run = MagicMock()
    run.hyperlink = hl

    para = _make_paragraph_mock(hyperlinks=[], runs=[run])
    doc_mock.paragraphs = [para]
    mock_document.return_value = doc_mock

    result = await parser.extract_links("fake.docx")

    assert len(result) == 1
    assert result[0].type == "external"
    assert result[0].uri == "https://fallback.example.com"


# ---------------------------------------------------------------------------
# 4 — Malformed hyperlink (bad rel_id) silently skipped
# ---------------------------------------------------------------------------


@patch("docx.Document")
@pytest.mark.asyncio
async def test_extract_malformed_hyperlink_skipped(mock_document, parser):
    """Hyperlink with rel_id not in doc.part.rels should be silently skipped."""
    doc_mock = _make_doc_mock()

    # Good hyperlink — rel_id exists in rels
    good_hl = _make_hyperlink_mock(rel_id="rId_good")
    doc_mock.part.rels["rId_good"] = MagicMock(target_ref="https://good.example.com")

    # Bad hyperlink — rel_id not present in doc.part.rels
    bad_hl = _make_hyperlink_mock(rel_id="rId_missing")

    para = _make_paragraph_mock(hyperlinks=[good_hl, bad_hl], runs=[])
    doc_mock.paragraphs = [para]
    mock_document.return_value = doc_mock

    result = await parser.extract_links("fake.docx")

    # Only the good link should appear in the result
    assert len(result) == 1
    assert result[0].uri == "https://good.example.com"


# ---------------------------------------------------------------------------
# 5 — Invalid file propagates error
# ---------------------------------------------------------------------------


@patch("docx.Document")
@pytest.mark.asyncio
async def test_extract_invalid_file(mock_document, parser):
    """Non-existent file should propagate an exception."""
    mock_document.side_effect = FileNotFoundError("No such file: nonexistent.docx")

    with pytest.raises(FileNotFoundError, match="No such file"):
        await parser.extract_links("nonexistent.docx")

    mock_document.assert_called_once_with("nonexistent.docx")


# ---------------------------------------------------------------------------
# 6 — Multiple paragraphs / multiple links
# ---------------------------------------------------------------------------


@patch("docx.Document")
@pytest.mark.asyncio
async def test_extract_multiple_paragraphs_multiple_links(mock_document, parser):
    """Multiple paragraphs each with multiple links extracts all correctly."""
    doc_mock = _make_doc_mock()

    hl1 = _make_hyperlink_mock(rel_id="rId1")
    doc_mock.part.rels["rId1"] = MagicMock(target_ref="https://first.example.com")
    para1 = _make_paragraph_mock(hyperlinks=[hl1], runs=[])

    hl2 = _make_hyperlink_mock(rel_id="rId2")
    doc_mock.part.rels["rId2"] = MagicMock(target_ref="https://second.example.com")
    hl3 = _make_hyperlink_mock(rel_id="rId3")
    doc_mock.part.rels["rId3"] = MagicMock(target_ref="https://third.example.com")
    para2 = _make_paragraph_mock(hyperlinks=[hl2, hl3], runs=[])

    doc_mock.paragraphs = [para1, para2]
    mock_document.return_value = doc_mock

    result = await parser.extract_links("fake.docx")

    assert len(result) == 3
    uris = [link.uri for link in result]
    assert "https://first.example.com" in uris
    assert "https://second.example.com" in uris
    assert "https://third.example.com" in uris
    assert all(link.type == "external" for link in result)


# ---------------------------------------------------------------------------
# 7 — Fallback from rel_id to rId attribute
# ---------------------------------------------------------------------------


@patch("docx.Document")
@pytest.mark.asyncio
async def test_extract_uses_rid_when_rel_id_missing(mock_document, parser):
    """Fallback from rel_id to rId attribute works for hyperlinks."""
    doc_mock = _make_doc_mock()

    # Hyperlink with rId set but rel_id = None
    hl = MagicMock()
    hl.rel_id = None
    hl.rId = "rId_from_rId"
    doc_mock.part.rels["rId_from_rId"] = MagicMock(
        target_ref="https://rId.example.com"
    )

    para = _make_paragraph_mock(hyperlinks=[hl], runs=[])
    doc_mock.paragraphs = [para]
    mock_document.return_value = doc_mock

    result = await parser.extract_links("fake.docx")

    assert len(result) == 1
    assert result[0].uri == "https://rId.example.com"
