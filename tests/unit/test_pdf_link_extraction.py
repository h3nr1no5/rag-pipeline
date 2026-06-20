"""Unit tests for PDFParser.extract_links().

Tests cover:
- PDF with no links returns empty list
- Internal links (LINK_GOTO) are extracted with correct type/source/target
- External URI links (LINK_URI) are extracted with correct type/uri
- Non-existent file raises an exception
"""

import pytest
from pathlib import Path
from src.infrastructure.parsers.base import PDFParser


@pytest.fixture
def parser() -> PDFParser:
    """Fixture providing a PDFParser instance."""
    return PDFParser()


def _create_minimal_pdf(tmp_path: Path, pages: int = 1) -> Path:
    """Create a minimal PDF with the given number of pages and return its path."""
    import fitz

    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    filepath = tmp_path / "minimal.pdf"
    doc.save(str(filepath))
    doc.close()
    return filepath


@pytest.mark.asyncio
async def test_extract_no_links(parser: PDFParser, tmp_path: Path) -> None:
    """PDF with no links should return an empty list."""
    filepath = _create_minimal_pdf(tmp_path, pages=1)
    links = await parser.extract_links(str(filepath))
    assert links == []


@pytest.mark.asyncio
async def test_extract_internal_link(parser: PDFParser, tmp_path: Path) -> None:
    """PDF with a LINK_GOTO to another page returns LinkInfo with type='internal'."""
    import fitz

    # Create a 2-page PDF
    doc = fitz.open()
    doc.new_page()  # page 0 (source)
    doc.new_page()  # page 1 (target)
    page0 = doc[0]

    bbox = fitz.Rect(50, 50, 200, 100)
    page0.insert_link({
        "kind": fitz.LINK_GOTO,
        "page": 1,       # 0-indexed target page
        "from": bbox,
    })

    filepath = tmp_path / "internal_link.pdf"
    doc.save(str(filepath))
    doc.close()

    links = await parser.extract_links(str(filepath))
    assert len(links) == 1

    link = links[0]
    assert link.type == "internal"
    assert link.source_page == 1        # page numbering starts at 1
    assert link.target_page == 2        # page 1 (0-indexed) -> 2 (1-indexed)
    assert link.uri is None
    assert link.bbox == tuple(bbox)


@pytest.mark.asyncio
async def test_extract_external_link(parser: PDFParser, tmp_path: Path) -> None:
    """PDF with a LINK_URI returns LinkInfo with type='external' and the URI."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()

    uri = "https://example.com/test"
    bbox = fitz.Rect(50, 50, 200, 100)
    page.insert_link({
        "kind": fitz.LINK_URI,
        "uri": uri,
        "from": bbox,
    })

    filepath = tmp_path / "external_link.pdf"
    doc.save(str(filepath))
    doc.close()

    links = await parser.extract_links(str(filepath))
    assert len(links) == 1

    link = links[0]
    assert link.type == "external"
    assert link.uri == uri
    assert link.source_page == 1
    assert link.target_page is None
    assert link.bbox == tuple(bbox)


@pytest.mark.asyncio
async def test_extract_invalid_file(parser: PDFParser) -> None:
    """Non-existent file should propagate an exception."""
    nonexistent = "/tmp/this_file_does_not_exist_12345.pdf"
    with pytest.raises(Exception):
        await parser.extract_links(nonexistent)


@pytest.mark.asyncio
async def test_extract_multiple_links(parser: PDFParser, tmp_path: Path) -> None:
    """A PDF with both internal and external links extracts all of them."""
    import fitz

    doc = fitz.open()
    doc.new_page()  # page 0
    doc.new_page()  # page 1 — used as target
    page0 = doc[0]

    # Add an internal link
    page0.insert_link({
        "kind": fitz.LINK_GOTO,
        "page": 1,
        "from": fitz.Rect(50, 50, 200, 100),
    })
    # Add an external link
    page0.insert_link({
        "kind": fitz.LINK_URI,
        "uri": "https://example.com",
        "from": fitz.Rect(250, 50, 400, 100),
    })

    filepath = tmp_path / "multiple_links.pdf"
    doc.save(str(filepath))
    doc.close()

    links = await parser.extract_links(str(filepath))
    assert len(links) == 2

    internal = next(link for link in links if link.type == "internal")
    external = next(link for link in links if link.type == "external")

    assert internal.source_page == 1
    assert internal.target_page == 2

    assert external.source_page == 1
    assert external.uri == "https://example.com"
