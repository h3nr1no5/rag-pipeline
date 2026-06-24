"""Unit tests for DOCX extraction: parser, table detection, converter, PDF fallback.

Task 9.2 — Tests use synthetic in-memory DOCX fixtures created with python-docx.
"""

import io
from pathlib import Path

import pytest
from docx import Document

from src.domain.rag.api_docs.extraction.converter import DocumentConverter
from src.domain.rag.api_docs.extraction.docx_parser import (
    DocxParser,
    RawDocument,
    RawParagraph,
    RawTable,
)
from src.domain.rag.api_docs.extraction.pdf_fallback import PdfFallbackExtractor
from src.domain.rag.api_docs.extraction.table_detector import (
    TableDetector,
    merge_multi_row_functions,
)

# ---------------------------------------------------------------------------
# Fixture helpers — synthetic DOCX creation
# ---------------------------------------------------------------------------


def _make_docx_buffer() -> io.BytesIO:
    """Create a synthetic DOCX with method, property, enum, and error-code tables."""
    doc = Document()
    doc.add_heading("Test API Docs", level=1)
    doc.add_heading("INode Interface", level=2)
    doc.add_paragraph("Interface for node operations.")

    # -- Method table --
    table = doc.add_table(rows=3, cols=4)
    headers = ["Method", "Parameters", "Return Type", "Description"]
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h
    table.rows[1].cells[0].text = "Create"
    table.rows[1].cells[1].text = "x: double\ny: double\nz: double"
    table.rows[1].cells[2].text = "void"
    table.rows[1].cells[3].text = "Creates a new node"
    # Multi-row function: first cell empty → continuation
    table.rows[2].cells[0].text = "AddNode"
    table.rows[2].cells[1].text = "parent: INode"
    table.rows[2].cells[2].text = "INode"
    table.rows[2].cells[3].text = "Adds a child node"

    # -- Property table --
    headers2 = ["Name", "Type", "Access", "Description"]
    table2 = doc.add_table(rows=2, cols=4)
    for i, h in enumerate(headers2):
        table2.rows[0].cells[i].text = h
    table2.rows[1].cells[0].text = "ChildCount"
    table2.rows[1].cells[1].text = "int"
    table2.rows[1].cells[2].text = "read"
    table2.rows[1].cells[3].text = "Number of children"

    # -- Enum table --
    headers3 = ["Name", "Value", "Description"]
    table3 = doc.add_table(rows=3, cols=3)
    for i, h in enumerate(headers3):
        table3.rows[0].cells[i].text = h
    table3.rows[1].cells[0].text = "None"
    table3.rows[1].cells[1].text = "0"
    table3.rows[1].cells[2].text = "No value"
    table3.rows[2].cells[0].text = "Active"
    table3.rows[2].cells[1].text = "1"

    # -- Error code table --
    headers4 = ["Error Code", "Description"]
    table4 = doc.add_table(rows=2, cols=2)
    for i, h in enumerate(headers4):
        table4.rows[0].cells[i].text = h
    table4.rows[1].cells[0].text = "0x80070057"
    table4.rows[1].cells[1].text = "Invalid argument"

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def _make_simple_docx() -> io.BytesIO:
    """Create a DOCX without tables (paragraphs only)."""
    doc = Document()
    doc.add_heading("Simple", level=1)
    doc.add_paragraph("Just a paragraph.")
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# DocxParser
# ---------------------------------------------------------------------------


def _write_docx(buffer: io.BytesIO, tmp_path: Path) -> Path:
    """Write docx buffer to a temporary file and return the path."""
    file_path = tmp_path / "test_api_docs.docx"
    file_path.write_bytes(buffer.getvalue())
    return file_path


@pytest.fixture
def docx_path(tmp_path: Path) -> Path:
    """Create a synthetic DOCX and return its path."""
    return _write_docx(_make_docx_buffer(), tmp_path)


@pytest.fixture
def simple_docx_path(tmp_path: Path) -> Path:
    """Create a simple DOCX and return its path."""
    return _write_docx(_make_simple_docx(), tmp_path)


def test_docx_parser_opens_and_reads(docx_path: Path):
    """DocxParser reads a DOCX and returns a RawDocument with paragraphs and tables."""
    parser = DocxParser(str(docx_path))
    raw = parser.parse()
    assert isinstance(raw, RawDocument)
    assert raw.filename == "test_api_docs.docx"
    assert len(raw.paragraphs) >= 3  # 2 headings + 1 paragraph
    assert len(raw.tables) == 4  # method, property, enum, error_code


def test_docx_parser_heading_levels(docx_path: Path):
    """Paragraphs from headings have correct heading_level."""
    parser = DocxParser(str(docx_path))
    raw = parser.parse()
    # Find the heading paragraphs
    headings = [p for p in raw.paragraphs if p.heading_level >= 0]
    assert len(headings) >= 2
    # First heading is level 1, second is level 2
    assert headings[0].heading_level == 1  # "Test API Docs"
    assert headings[1].heading_level == 2  # "INode Interface"


def test_docx_parser_extracts_table_rows(docx_path: Path):
    """Tables have correct header and row data."""
    parser = DocxParser(str(docx_path))
    raw = parser.parse()
    # First table = method table with 2 data rows
    method_table = raw.tables[0]
    assert len(method_table.headers) == 4
    assert "Method" in method_table.headers
    assert len(method_table.rows) == 2
    assert method_table.rows[0][0] == "Create"


def test_docx_parser_no_tables(simple_docx_path: Path):
    """Parser handles DOCX with no tables."""
    parser = DocxParser(str(simple_docx_path))
    raw = parser.parse()
    assert len(raw.tables) == 0
    assert len(raw.paragraphs) >= 1


# ---------------------------------------------------------------------------
# TableDetector
# ---------------------------------------------------------------------------

DETECTOR = TableDetector()


def test_detect_method_table():
    """TableDetector identifies a method table by its headers."""
    table = RawTable(
        headers=["Method", "Parameters", "Return Type", "Description"],
        rows=[["Foo", "x: int", "void", "Does foo"]],
    )
    assert DETECTOR.detect(table) == "method"


def test_detect_property_table():
    """TableDetector identifies a property table."""
    table = RawTable(
        headers=["Name", "Type", "Access", "Description"],
        rows=[["Prop", "int", "read", "A property"]],
    )
    assert DETECTOR.detect(table) == "property"


def test_detect_enum_table():
    """TableDetector identifies an enum table."""
    table = RawTable(
        headers=["Value", "Description"],
        rows=[["0", "None"]],
    )
    assert DETECTOR.detect(table) == "enum"


def test_detect_error_code_table():
    """TableDetector identifies an error code table."""
    table = RawTable(
        headers=["Error Code", "Description"],
        rows=[["0x80070057", "Invalid arg"]],
    )
    assert DETECTOR.detect(table) == "error_code"


def test_detect_unknown_table():
    """TableDetector returns 'unknown' for unrecognised headers."""
    table = RawTable(
        headers=["Random", "Stuff"],
        rows=[["a", "b"]],
    )
    assert DETECTOR.detect(table) == "unknown"


def test_detect_empty_headers():
    """TableDetector returns 'unknown' for empty headers."""
    table = RawTable(headers=[], rows=[])
    assert DETECTOR.detect(table) == "unknown"


# ---------------------------------------------------------------------------
# merge_multi_row_functions
# ---------------------------------------------------------------------------


def test_merge_multi_row_functions_merges():
    """Merges continuation rows where first cell is empty."""
    table = RawTable(
        headers=["Method", "Parameters", "Return Type", "Description"],
        rows=[
            ["CreateNode", "x: double\ny: double", "INode", "Creates"],
            ["", "z: double", "", ""],  # continuation of previous (first cell empty)
            ["DeleteNode", "id: int", "void", "Deletes"],
        ],
    )
    merged = merge_multi_row_functions([table])
    assert len(merged) == 1
    result = merged[0]
    assert len(result.rows) == 2  # CreateNode (merged) + DeleteNode
    assert result.rows[0][0] == "CreateNode"
    # Parameters from continuation row should be appended
    assert "z: double" in result.rows[0][1]


def test_merge_multi_row_functions_no_continuation():
    """Table without continuation rows is returned unchanged."""
    table = RawTable(
        headers=["Method", "Parameters", "Return", "Description"],
        rows=[
            ["Foo", "x: int", "void", "Does foo"],
            ["Bar", "y: str", "int", "Does bar"],
        ],
    )
    merged = merge_multi_row_functions([table])
    assert len(merged[0].rows) == 2


def test_merge_multi_row_functions_single_row():
    """Single-row table is returned unchanged."""
    table = RawTable(
        headers=["Method", "Return"],
        rows=[["Foo", "void"]],
    )
    merged = merge_multi_row_functions([table])
    assert len(merged[0].rows) == 1
    assert merged[0].rows[0][0] == "Foo"


# ---------------------------------------------------------------------------
# DocumentConverter
# ---------------------------------------------------------------------------


def _make_raw_doc_for_converter() -> RawDocument:
    """Helper: create a RawDocument suitable for testing DocumentConverter."""
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2", heading_level=2, position=0),
    ]
    tables = [
        RawTable(
            headers=["Method", "Parameters", "Return Type", "Description"],
            rows=[["Create", "x: double\ny: double", "void", "Creates a node"]],
            position=1,
        ),
        RawTable(
            headers=["Name", "Type", "Access", "Description"],
            rows=[["Count", "int", "read", "The count"]],
            position=2,
        ),
        RawTable(
            headers=["Value", "Description"],
            rows=[["0", "None"]],
            position=3,
        ),
        RawTable(
            headers=["Error Code", "Description"],
            rows=[["0x80070057", "Invalid argument"]],
            position=4,
        ),
    ]
    return RawDocument(tables=tables, paragraphs=paragraphs, filename="test.docx")


def test_document_converter_method_table():
    """DocumentConverter converts a method table to APIFunction."""
    raw = _make_raw_doc_for_converter()
    table_types = {0: "method", 1: "property", 2: "enum", 3: "error_code"}
    merged = merge_multi_row_functions(raw.tables)
    converter = DocumentConverter()
    result = converter.convert(raw, table_types, merged)

    assert len(result["interfaces"]) == 1
    iface = result["interfaces"][0]
    assert iface.name == "INode"
    assert len(iface.methods) == 1
    assert iface.methods[0].name == "Create"
    assert len(iface.methods[0].parameters) == 2
    assert iface.methods[0].parameters[0].name == "x"


def test_document_converter_property_table():
    """DocumentConverter converts a property table."""
    raw = _make_raw_doc_for_converter()
    table_types = {0: "method", 1: "property", 2: "enum", 3: "error_code"}
    merged = merge_multi_row_functions(raw.tables)
    converter = DocumentConverter()
    result = converter.convert(raw, table_types, merged)

    iface = result["interfaces"][0]
    assert len(iface.properties) == 1
    assert iface.properties[0].name == "Count"
    assert iface.properties[0].type_annotation == "int"


def test_document_converter_enum_table():
    """DocumentConverter converts an enum table."""
    raw = _make_raw_doc_for_converter()
    table_types = {0: "method", 1: "property", 2: "enum", 3: "error_code"}
    merged = merge_multi_row_functions(raw.tables)
    converter = DocumentConverter()
    result = converter.convert(raw, table_types, merged)

    assert len(result["enums"]) == 1
    enum_def = result["enums"][0]
    assert len(enum_def.values) == 1
    assert enum_def.values[0].name == "0"
    assert enum_def.values[0].value == 0


def test_document_converter_error_code_table():
    """DocumentConverter converts an error code table."""
    raw = _make_raw_doc_for_converter()
    table_types = {0: "method", 1: "property", 2: "enum", 3: "error_code"}
    merged = merge_multi_row_functions(raw.tables)
    converter = DocumentConverter()
    result = converter.convert(raw, table_types, merged)

    assert len(result["error_codes"]) == 1
    ec = result["error_codes"][0]
    assert ec.name == "0x80070057"
    assert ec.code == 0x80070057


# ---------------------------------------------------------------------------
# PdfFallbackExtractor
# ---------------------------------------------------------------------------

# Note: Full PDF integration test is in tests/integration/test_api_docs_pdf_fallback.py
# Here we test that the class can be instantiated and has the expected interface.


def test_pdf_fallback_extractor_instantiation():
    """PdfFallbackExtractor can be instantiated with a path."""
    extractor = PdfFallbackExtractor("/nonexistent/test.pdf")
    assert extractor.file_path.name == "test.pdf"


def test_pdf_fallback_extractor_raises_on_missing_file():
    """PdfFallbackExtractor raises when the file does not exist."""
    extractor = PdfFallbackExtractor("/nonexistent/missing.pdf")
    with pytest.raises(Exception):
        extractor.extract()
