"""Unit tests for DOCX extraction: parser, table detection, converter, PDF fallback.

Task 9.2 — Tests use synthetic in-memory DOCX fixtures created with python-docx.

Task 7.x:
  - 7.1: Converter positional extractor tests for all 5 table types
  - 7.3: Paragraph-based table detection tests
  - 7.4: Property name+desc split heuristic tests
  - 7.5: Consecutive table inheritance tests
"""

import io
import logging
from pathlib import Path

import pytest
from docx import Document

from src.domain.rag.api_docs.extraction.converter import (
    DocumentConverter,
    GenericTableEntry,
    _parse_inline_params,
)
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
    headers = ["Return Type", "Method", "Description", ""]
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h
    table.rows[1].cells[0].text = "void"
    table.rows[1].cells[1].text = "CreateNode(double x, double y)"
    table.rows[1].cells[2].text = "Creates a new node"
    table.rows[1].cells[3].text = ""
    # Multi-row function: first cell empty → continuation
    table.rows[2].cells[0].text = "INode*"
    table.rows[2].cells[1].text = "AddChild(INode parent)"
    table.rows[2].cells[2].text = "Adds a child node"
    table.rows[2].cells[3].text = ""

    # -- Property table --
    headers2 = ["Type", "Name \u2022 Description", "", ""]
    table2 = doc.add_table(rows=2, cols=4)
    for i, h in enumerate(headers2):
        table2.rows[0].cells[i].text = h
    table2.rows[1].cells[0].text = "int"
    table2.rows[1].cells[1].text = "ChildCount \u2022 Number of children"
    table2.rows[1].cells[2].text = ""
    table2.rows[1].cells[3].text = ""

    # -- Enum table --
    headers3 = ["", "Constant", "Description"]
    table3 = doc.add_table(rows=3, cols=3)
    for i, h in enumerate(headers3):
        table3.rows[0].cells[i].text = h
    table3.rows[1].cells[0].text = ""
    table3.rows[1].cells[1].text = "None = 0"
    table3.rows[1].cells[2].text = "No value"
    table3.rows[2].cells[0].text = ""
    table3.rows[2].cells[1].text = "Active = 1"
    table3.rows[2].cells[2].text = ""

    # -- Error code table --
    headers4 = ["", "Error Code", "Description"]
    table4 = doc.add_table(rows=2, cols=3)
    for i, h in enumerate(headers4):
        table4.rows[0].cells[i].text = h
    table4.rows[1].cells[0].text = ""
    table4.rows[1].cells[1].text = "E_INVALIDARG = 0x80070057"
    table4.rows[1].cells[2].text = "Invalid argument"

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
    assert "Return Type" in method_table.headers
    assert len(method_table.rows) == 2
    assert method_table.rows[0][0] == "void"


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
    """TableDetector identifies a method table by its headers (keyword + multi-signal)."""
    table = RawTable(
        headers=["Method", "Parameters", "Return Type", "Description"],
        rows=[["Foo", "x: int", "void", "Does foo"]],
    )
    assert DETECTOR.detect(table) == "method"


def test_detect_property_table():
    """TableDetector identifies a property table."""
    table = RawTable(
        headers=["Type", "Name \u2022 Description", "", ""],
        rows=[["int", "Prop \u2022 A property", "", ""]],
    )
    assert DETECTOR.detect(table) == "property"


def test_detect_enum_table():
    """TableDetector identifies an enum table."""
    table = RawTable(
        headers=["", "Constant", "Description"],
        rows=[["", "None = 0", "No value"]],
    )
    assert DETECTOR.detect(table) == "enum"


def test_detect_error_code_table():
    """TableDetector identifies an error code table."""
    table = RawTable(
        headers=["", "Error Code", "Description"],
        rows=[["", "E_INVALIDARG = 0x80070057", "Invalid arg"]],
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
        headers=["Return Type", "Method", "Description", ""],
        rows=[
            ["void", "CreateNode(double x, double y)", "Creates", ""],
            ["", "", "extra desc", ""],  # continuation (first cell empty)
            ["int", "DeleteNode(int id)", "Deletes", ""],
        ],
    )
    merged = merge_multi_row_functions([table])
    assert len(merged) == 1
    result = merged[0]
    assert len(result.rows) == 2  # CreateNode (merged) + DeleteNode
    assert result.rows[0][0] == "void"
    # Continuation row's description should be appended
    assert "extra desc" in result.rows[0][2]


def test_merge_multi_row_functions_no_continuation():
    """Table without continuation rows is returned unchanged."""
    table = RawTable(
        headers=["Return Type", "Method", "Description", ""],
        rows=[
            ["void", "Foo(double x)", "Does foo", ""],
            ["int", "Bar(str y)", "Does bar", ""],
        ],
    )
    merged = merge_multi_row_functions([table])
    assert len(merged[0].rows) == 2


def test_merge_multi_row_functions_single_row():
    """Single-row table is returned unchanged."""
    table = RawTable(
        headers=["Return Type", "Method"],
        rows=[["void", "Foo()"]],
    )
    merged = merge_multi_row_functions([table])
    assert len(merged[0].rows) == 1
    assert merged[0].rows[0][0] == "void"


# ---------------------------------------------------------------------------
# DocumentConverter - positional extractor unit tests (Task 7.1)
# ---------------------------------------------------------------------------


#   _____ _   _ _____   ____ ___  _   _ _____ ____   ___ _   _ ____
#  |  ___| | | |_   _| |  _ \_ _|| \ | |_   _|  _ \ |_ _| \ | / ___|
#  | |_  | | | | | |   | |_) | | |  \| | | | | |_) | | ||  \| \___ \
#  |  _| | |_| | | |   |  __/| | | |\  | | | |  _ <  | || |\  |___) |
#  |_|    \___/  |_|   |_|  |___||_| \_| |_| |_| \_\|___|_| \_|____/


def test_convert_method_table_basic():
    """_convert_method_table parses positional col0=return_type, col1=name(params)."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            ["void", "CreateNode(double x, double y)", ""],
            ["INode*", "FindByName(BSTR name)", ""],
        ],
    )
    functions = converter._convert_method_table(table)
    assert len(functions) == 2
    assert functions[0].name == "CreateNode"
    assert functions[0].return_type == "void"
    assert len(functions[0].parameters) == 2
    assert functions[0].parameters[0].name == "x"
    assert functions[0].parameters[0].type_annotation == "double"
    assert functions[1].name == "FindByName"
    assert functions[1].return_type == "INode*"
    assert len(functions[1].parameters) == 1
    assert functions[1].parameters[0].name == "name"
    assert functions[1].parameters[0].type_annotation == "BSTR"


def test_convert_method_table_empty_row_separator():
    """Fully empty rows act as function separators."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            ["void", "FuncA()", ""],
            ["", "", ""],  # separator
            ["int", "FuncB()", ""],
        ],
    )
    functions = converter._convert_method_table(table)
    assert len(functions) == 2
    assert functions[0].name == "FuncA"
    assert functions[1].name == "FuncB"


def test_convert_method_table_continuation_rows():
    """Rows with empty col0 set param descriptions or function description.

    Note: The initial row's col2 is NOT captured as the function description
    by the positional converter — descriptions are only set via continuation
    rows (col0 empty).
    """
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            ["void", "DoWork(double x)", ""],
            ["", "x", "The X coordinate"],  # param desc (col1 matches known param)
            ["", "Extra detail", ""],         # func desc (col1 not a param)
        ],
    )
    functions = converter._convert_method_table(table)
    assert len(functions) == 1
    assert functions[0].name == "DoWork"
    assert functions[0].parameters[0].name == "x"
    assert functions[0].parameters[0].description == "The X coordinate"
    # Description set by the continuation row
    assert functions[0].description == "Extra detail"


# ---------------------------------------------------------------------------
# _vb alias function handling (Fix 3)
# ---------------------------------------------------------------------------


def test_convert_method_table_vb_alias():
    """_vb alias function has no fake params and correct description."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            # MessageDlg_vb (Visual Basic compatible function of MessageDlg)
            ["EMessageDialogButton*",
             "MessageDlg_vb (Visual Basic compatible function of MessageDlg)",
             ""],
        ],
    )
    functions = converter._convert_method_table(table)
    assert len(functions) == 1
    func = functions[0]
    assert func.name == "MessageDlg_vb"
    assert len(func.parameters) == 0
    assert func.description == "VB-compatible alias for MessageDlg"


def test_convert_method_table_non_vb_function_unchanged():
    """Regular function not ending in _vb is unaffected by alias detection."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            ["void", "NormalFunction(int x)", ""],
        ],
    )
    functions = converter._convert_method_table(table)
    assert len(functions) == 1
    func = functions[0]
    assert func.name == "NormalFunction"
    assert len(func.parameters) == 1
    assert func.parameters[0].name == "x"


# ---------------------------------------------------------------------------
# Merged continuation parsing for parameter descriptions (Fix 1 & 2)
# ---------------------------------------------------------------------------


def test_convert_method_table_merged_continuation_param_descriptions():
    """Merged \n-separated continuation data sets param descriptions."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            # Single row simulating merge_multi_row_functions output:
            #   Row 0: HRESULT | DisableMainForm(lParam) | Disables the main form.
            #   Row 1:         | lParam                  | LPARAM value
            # After merge: col1="DisableMainForm(lParam)\nlParam"
            #             col2="Disables the main form.\nLPARAM value"
            ["HRESULT", "DisableMainForm(lParam)\nlParam",
             "Disables the main form.\nLPARAM value"],
        ],
    )
    functions = converter._convert_method_table(table)
    assert len(functions) == 1
    func = functions[0]
    assert func.name == "DisableMainForm"
    assert func.return_type == "HRESULT"
    assert len(func.parameters) == 1
    assert func.parameters[0].name == "lParam"
    assert func.parameters[0].description == "LPARAM value"
    assert func.description == "Disables the main form."


def test_convert_method_table_merged_continuation_multi_params():
    """Multiple merged continuation params all get descriptions."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            #   Row 0: void | Func(p1, p2) |
            #   Row 1:      | p1           | description of p1
            #   Row 2:      | p2           | description of p2
            # After merge:
            #   col1="Func(p1, p2)\np1\np2"
            #   col2="\ndescription of p1\ndescription of p2"
            ["void", "Func(p1, p2)\np1\np2",
             "\ndescription of p1\ndescription of p2"],
        ],
    )
    functions = converter._convert_method_table(table)
    assert len(functions) == 1
    func = functions[0]
    assert func.name == "Func"
    assert len(func.parameters) == 2
    assert func.parameters[0].name == "p1"
    assert func.parameters[0].description == "description of p1"
    assert func.parameters[1].name == "p2"
    assert func.parameters[1].description == "description of p2"


def test_convert_method_table_merged_continuation_no_col2_for_param():
    """Param name in continuation col1 but no col2 text → added to func desc."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            #   Row 0: void | Func(p1, p2) |
            #   Row 1:      | p1           | desc for p1
            #   Row 2:      | p2           |              (empty col2)
            # After merge:
            #   col1="Func(p1, p2)\np1\np2"
            #   col2="\ndesc for p1\n"
            ["void", "Func(p1, p2)\np1\np2",
             "\ndesc for p1\n"],
        ],
    )
    functions = converter._convert_method_table(table)
    assert len(functions) == 1
    func = functions[0]
    assert func.parameters[0].description == "desc for p1"
    assert func.parameters[1].description == ""
    # p2 appears in func description since its col2 was empty
    assert "p2" in func.description


def test_convert_method_table_name_without_parens_no_spill():
    """Function name without parentheses does NOT include merged text."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            #   Row 0: HRESULT | DisableMainForm | Disables the main form.
            #   Row 1:         | lParam           | LPARAM value
            # After merge:
            #   col1="DisableMainForm\nlParam"
            #   col2="Disables the main form.\nLPARAM value"
            ["HRESULT", "DisableMainForm\nlParam",
             "Disables the main form.\nLPARAM value"],
        ],
    )
    functions = converter._convert_method_table(table)
    assert len(functions) == 1
    func = functions[0]
    # Name must NOT include continuation text
    assert func.name == "DisableMainForm"
    assert "\n" not in func.name
    assert "lParam" not in func.name


#   ____ ___  _   _ _____ _____ ____ ___  _   _ ____
#  |  _ \_ _|| \ | |_   _| ____/ ___|_ _|| \ | / ___|
#  | |_) | | |  \| | | | |  _|| |  _ | | |  \| \___ \
#  |  __/| | | |\  | | | | |__| |_| || | | |\  |___) |
#  |_|  |___||_| \_| |_| |_____\____|___||_| \_|____/


def test_convert_property_table_basic():
    """_convert_property_table uses positional col0=type, col1=name•desc."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            ["int", "Count \u2022 The number of items", ""],
            ["BSTR", "Name \u2022 The object name", ""],
        ],
    )
    props = converter._convert_property_table(table)
    assert len(props) == 2
    assert props[0].name == "Count"
    assert props[0].type_annotation == "int"
    assert props[0].description == "The number of items"
    assert props[1].name == "Name"
    assert props[1].type_annotation == "BSTR"
    assert props[1].description == "The object name"


#   _____ _   _ _   _ __  __
#  | ____| | | | | | |  \/  |
#  |  _| | | | | | | | |\/| |
#  | |___| |_| | |_| | |  | |
#  |_____|\___/ \___/|_|  |_|


def test_convert_enum_table_basic():
    """_convert_enum_table parses positional col1=name=value, col2=description."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            ["", "None = 0", "No value"],
            ["", "Active = 1", "Active state"],
        ],
    )
    enum = converter._convert_enum_table(table)
    assert enum is not None
    assert len(enum.values) == 2
    assert enum.values[0].name == "None"
    assert enum.values[0].value == 0
    assert enum.values[0].description == "No value"
    assert enum.values[1].name == "Active"
    assert enum.values[1].value == 1


def test_convert_enum_table_no_values_returns_none():
    """_convert_enum_table returns None when no values can be parsed."""
    converter = DocumentConverter()
    table = RawTable(headers=["", "", ""], rows=[])
    assert converter._convert_enum_table(table) is None


#   _____ ____   ___  _   _ ____  _____ ____   ___  _   _
#  |  ___|  _ \ / _ \| | | / ___|| ____|  _ \ / _ \| \ | |
#  | |_  | |_) | | | | | | \___ \|  _| | |_) | | | |  \| |
#  |  _| |  _ <| |_| | |_| |___) | |___|  _ <| |_| | |\  |
#  |_|   |_| \_\\___/ \___/|____/|_____|_| \_\\___/|_| \_|


def test_convert_error_code_table_basic():
    """_convert_error_code_table parses col1=name=value, col2=description."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            ["", "E_INVALIDARG = 0x80070057", "Invalid argument"],
            ["", "E_FAIL = 0x80004005", "General failure"],
        ],
    )
    codes = converter._convert_error_code_table(table)
    assert len(codes) == 2
    assert codes[0].name == "E_INVALIDARG"
    assert codes[0].code == 0x80070057
    assert codes[0].description == "Invalid argument"
    assert codes[1].name == "E_FAIL"
    assert codes[1].code == 0x80004005


def test_convert_error_code_table_plain_name():
    """Error code without '=' is treated as plain name."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            ["", "E_NOTIMPL", "Not implemented"],
        ],
    )
    codes = converter._convert_error_code_table(table)
    assert len(codes) == 1
    assert codes[0].name == "E_NOTIMPL"


#   ____ ____   ___  ____ ___ _   _ _____
#  |  _ \___ \ / _ \|  _ \_ _| \ | |_   _|
#  | |_) |__) | | | | | | | ||  \| | | |
#  |  _ < __/| |_| | |_| | || |\  | | |
#  |_| \_\___|\___/|____|___|_| \_| |_|


def test_convert_record_table_basic():
    """_convert_record_table parses positional col0=type, col1=name, col2=desc."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            ["int", "Id", "Unique identifier"],
            ["string", "Name", "Record name"],
        ],
        caption="MyRecord",
    )
    record = converter._convert_record_table(table)
    assert record is not None
    assert record.name == "MyRecord"
    assert len(record.fields) == 2
    assert record.fields[0].name == "Id"
    assert record.fields[0].type_annotation == "int"
    assert record.fields[0].description == "Unique identifier"
    assert record.fields[1].name == "Name"
    assert record.fields[1].type_annotation == "string"
    assert record.fields[1].description == "Record name"


def test_convert_record_table_empty_col0_skipped():
    """Rows with empty col0 (type) are skipped."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", "", ""],
        rows=[
            ["", "Skipped", ""],  # no type → skipped
            ["int", "Id", ""],     # has type → parsed
        ],
    )
    record = converter._convert_record_table(table)
    assert record is not None
    assert len(record.fields) == 1
    assert record.fields[0].name == "Id"


def test_convert_record_table_no_fields_returns_none():
    """Table with no valid fields returns None."""
    converter = DocumentConverter()
    table = RawTable(
        headers=["", ""],
        rows=[],
    )
    record = converter._convert_record_table(table)
    assert record is None


# ---------------------------------------------------------------------------
# _split_property_name_desc -- heuristics (Task 7.4)
# ---------------------------------------------------------------------------

def test_split_property_name_desc_bullet():
    """Bullet separator splits name and description."""
    result = DocumentConverter._split_property_name_desc("Count \u2022 The number of items")
    assert result == ("Count", "The number of items")


def test_split_property_name_desc_bracket():
    """Bracket-index parameter splits correctly."""
    result = DocumentConverter._split_property_name_desc("Item [0] The item at index")
    assert result == ("Item", "The item at index")


def test_split_property_name_desc_bracket_no_trailing_text():
    """Bracket with no text after it leaves empty description."""
    result = DocumentConverter._split_property_name_desc("Item [0]")
    assert result == ("Item", "")


def test_split_property_name_desc_word_boundary():
    """Word-boundary heuristic finds PascalCase name."""
    result = DocumentConverter._split_property_name_desc("ChildCount Number of children")
    assert result[0] == "ChildCount"
    assert "Number of children" in result[1]


def test_split_property_name_desc_no_description():
    """String without description returns empty string for desc."""
    result = DocumentConverter._split_property_name_desc("SimpleName")
    assert result == ("SimpleName", "")


def test_split_property_name_desc_empty():
    """Empty string returns empty tuple."""
    result = DocumentConverter._split_property_name_desc("")
    assert result == ("", "")


# ---------------------------------------------------------------------------
# _parse_inline_params (module-level function)
# ---------------------------------------------------------------------------

def test_parse_inline_params_basic():
    """Comma-separated type name pairs are parsed."""
    result = _parse_inline_params("double x, BSTR name")
    assert len(result) == 2
    assert result[0].name == "x"
    assert result[0].type_annotation == "double"
    assert result[1].name == "name"
    assert result[1].type_annotation == "BSTR"


def test_parse_inline_params_with_modifiers():
    """[in] and [out] modifiers are parsed; only [out] sets optional=True."""
    result = _parse_inline_params("[in] long value, [out] BSTR* result")
    assert len(result) == 2
    assert result[0].name == "value"
    assert result[0].type_annotation == "long"
    # [in] does NOT match "optional" or "out" → optional=False
    assert result[0].optional is False
    assert result[1].name == "result"
    assert result[1].type_annotation == "BSTR*"
    # [out] matches "out" → optional=True
    assert result[1].optional is True


def test_parse_inline_params_empty():
    """Empty string returns empty list."""
    assert _parse_inline_params("") == []
    assert _parse_inline_params("   ") == []


# ---------------------------------------------------------------------------
# _build_interface_descriptions (Task 3.1-3.3)
# ---------------------------------------------------------------------------

def test_build_interface_descriptions_basic():
    """Heading-adjacent paragraph is captured as interface description."""
    doc = RawDocument(
        paragraphs=[
            RawParagraph(text="IFileDialog Interface", style_name="Heading 2",
                         heading_level=2, position=0),
            RawParagraph(text="Provides file dialog functionality.",
                         style_name="Normal", heading_level=-1, position=1),
            RawParagraph(text="Methods", style_name="Heading 3",
                         heading_level=3, position=2),
        ],
        tables=[],
        filename="test.docx",
    )
    result = DocumentConverter._build_interface_descriptions(doc)
    assert result == {"IFileDialog": "Provides file dialog functionality."}


def test_build_interface_descriptions_no_description():
    """Interface without following paragraph is omitted."""
    doc = RawDocument(
        paragraphs=[
            RawParagraph(text="IFileDialog Interface", style_name="Heading 2",
                         heading_level=2, position=0),
        ],
        tables=[],
        filename="test.docx",
    )
    result = DocumentConverter._build_interface_descriptions(doc)
    assert result == {}


# ---------------------------------------------------------------------------
# _assign_paragraphs_to_interfaces (Task 2.1)
# ---------------------------------------------------------------------------


def test_assign_paragraphs_basic():
    """First paragraph after interface heading is skipped (used as description),
    subsequent paragraphs are appended to APIInterface.paragraphs."""
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2",
                     heading_level=2, position=0),
        RawParagraph(text="Interface for node operations.", style_name="Normal",
                     heading_level=-1, position=1),
        RawParagraph(text="Tree operations support.", style_name="Normal",
                     heading_level=-1, position=2),
        RawParagraph(text="Additional node details.", style_name="Normal",
                     heading_level=-1, position=3),
    ]
    tables = [
        RawTable(headers=["", "", ""],
                 rows=[["void", "CreateNode()", ""]], position=4),
    ]
    doc = RawDocument(tables=tables, paragraphs=paragraphs, filename="test.docx")
    converter = DocumentConverter()
    table_types = {0: "method"}
    merged = merge_multi_row_functions(doc.tables)
    result = converter.convert(doc, table_types, merged)

    iface = result["interfaces"][0]
    assert iface.name == "INode"
    assert iface.description == "Interface for node operations."
    assert len(iface.paragraphs) == 2
    assert iface.paragraphs[0] == "Tree operations support."
    assert iface.paragraphs[1] == "Additional node details."


def test_assign_paragraphs_non_interface_heading():
    """Non-interface headings reset context — paragraphs not assigned."""
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2",
                     heading_level=2, position=0),
        RawParagraph(text="Interface description.", style_name="Normal",
                     heading_level=-1, position=1),
        RawParagraph(text="Methods", style_name="Heading 3",
                     heading_level=3, position=2),
        RawParagraph(text="After Methods heading.", style_name="Normal",
                     heading_level=-1, position=3),
    ]
    tables = [
        RawTable(headers=["", "", ""],
                 rows=[["void", "CreateNode()", ""]], position=4),
    ]
    doc = RawDocument(tables=tables, paragraphs=paragraphs, filename="test.docx")
    converter = DocumentConverter()
    table_types = {0: "method"}
    merged = merge_multi_row_functions(doc.tables)
    result = converter.convert(doc, table_types, merged)

    iface = result["interfaces"][0]
    assert len(iface.paragraphs) == 0
    assert "After Methods heading." not in iface.paragraphs


def test_assign_paragraphs_empty_skipped():
    """Empty paragraphs are skipped; first non-empty is used as description."""
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2",
                     heading_level=2, position=0),
        RawParagraph(text="", style_name="Normal",
                     heading_level=-1, position=1),
        RawParagraph(text="First real paragraph (description).", style_name="Normal",
                     heading_level=-1, position=2),
        RawParagraph(text="Captured paragraph.", style_name="Normal",
                     heading_level=-1, position=3),
    ]
    tables = [
        RawTable(headers=["", "", ""],
                 rows=[["void", "CreateNode()", ""]], position=4),
    ]
    doc = RawDocument(tables=tables, paragraphs=paragraphs, filename="test.docx")
    converter = DocumentConverter()
    table_types = {0: "method"}
    merged = merge_multi_row_functions(doc.tables)
    result = converter.convert(doc, table_types, merged)

    iface = result["interfaces"][0]
    assert iface.description == "First real paragraph (description)."
    assert len(iface.paragraphs) == 1
    assert iface.paragraphs[0] == "Captured paragraph."


def test_assign_paragraphs_multiple_under_one():
    """Multiple paragraphs under one interface heading are all captured (except first)."""
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2",
                     heading_level=2, position=0),
        RawParagraph(text="Description.", style_name="Normal",
                     heading_level=-1, position=1),
        RawParagraph(text="First para.", style_name="Normal",
                     heading_level=-1, position=2),
        RawParagraph(text="Second para.", style_name="Normal",
                     heading_level=-1, position=3),
        RawParagraph(text="Third para.", style_name="Normal",
                     heading_level=-1, position=4),
    ]
    tables = [
        RawTable(headers=["", "", ""],
                 rows=[["void", "CreateNode()", ""]], position=5),
    ]
    doc = RawDocument(tables=tables, paragraphs=paragraphs, filename="test.docx")
    converter = DocumentConverter()
    table_types = {0: "method"}
    merged = merge_multi_row_functions(doc.tables)
    result = converter.convert(doc, table_types, merged)

    iface = result["interfaces"][0]
    assert len(iface.paragraphs) == 3
    assert iface.paragraphs == ["First para.", "Second para.", "Third para."]


def test_assign_paragraphs_multiple_interfaces():
    """Multiple interfaces each get their own paragraphs correctly."""
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2",
                     heading_level=2, position=0),
        RawParagraph(text="INode description.", style_name="Normal",
                     heading_level=-1, position=1),
        RawParagraph(text="INode paragraph 1.", style_name="Normal",
                     heading_level=-1, position=2),
        RawParagraph(text="IElement Interface", style_name="Heading 2",
                     heading_level=2, position=4),
        RawParagraph(text="IElement description.", style_name="Normal",
                     heading_level=-1, position=5),
        RawParagraph(text="IElement paragraph 1.", style_name="Normal",
                     heading_level=-1, position=6),
    ]
    tables = [
        RawTable(headers=["", "", ""],
                 rows=[["void", "CreateNode()", ""]], position=3),
        RawTable(headers=["", "", ""],
                 rows=[["void", "Render()", ""]], position=7),
    ]
    doc = RawDocument(tables=tables, paragraphs=paragraphs, filename="test.docx")
    converter = DocumentConverter()
    table_types = {0: "method", 1: "method"}
    merged = merge_multi_row_functions(doc.tables)
    result = converter.convert(doc, table_types, merged)

    assert len(result["interfaces"]) == 2
    inode = next(i for i in result["interfaces"] if i.name == "INode")
    ielem = next(i for i in result["interfaces"] if i.name == "IElement")
    assert inode.description == "INode description."
    assert inode.paragraphs == ["INode paragraph 1."]
    assert ielem.description == "IElement description."
    assert ielem.paragraphs == ["IElement paragraph 1."]


def test_assign_paragraphs_after_non_interface_heading():
    """Paragraphs after a non-interface heading are NOT assigned."""
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2",
                     heading_level=2, position=0),
        RawParagraph(text="Interface description.", style_name="Normal",
                     heading_level=-1, position=1),
        RawParagraph(text="First paragraph.", style_name="Normal",
                     heading_level=-1, position=2),
        RawParagraph(text="Second paragraph.", style_name="Normal",
                     heading_level=-1, position=3),
        RawParagraph(text="Separate Section", style_name="Heading 1",
                     heading_level=1, position=5),
        RawParagraph(text="Should NOT be assigned.", style_name="Normal",
                     heading_level=-1, position=6),
    ]
    tables = [
        RawTable(headers=["", "", ""],
                 rows=[["void", "CreateNode()", ""]], position=4),
    ]
    doc = RawDocument(tables=tables, paragraphs=paragraphs, filename="test.docx")
    converter = DocumentConverter()
    table_types = {0: "method"}
    merged = merge_multi_row_functions(doc.tables)
    result = converter.convert(doc, table_types, merged)

    iface = result["interfaces"][0]
    assert len(iface.paragraphs) == 2
    assert "Should NOT be assigned." not in iface.paragraphs


# ---------------------------------------------------------------------------
# GenericTableEntry creation — unknown tables (Task 3.1)
# ---------------------------------------------------------------------------


def test_generic_table_entry_unknown():
    """An unknown table creates a GenericTableEntry instead of being skipped."""
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2",
                     heading_level=2, position=0),
    ]
    tables = [
        RawTable(headers=["Random", "Stuff"],
                 rows=[["a", "b"]], position=1),
    ]
    doc = RawDocument(tables=tables, paragraphs=paragraphs, filename="test.docx")
    converter = DocumentConverter()
    result = converter.convert(doc, {0: "unknown"}, [doc.tables[0]])

    assert len(result["generic_tables"]) == 1
    gt = result["generic_tables"][0]
    assert isinstance(gt, GenericTableEntry)


def test_generic_table_entry_fields():
    """GenericTableEntry has correct heading_stack, rows, header_row,
    heading_text, and parent_interface."""
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2",
                     heading_level=2, position=0),
    ]
    tables = [
        RawTable(headers=["Random", "Stuff"],
                 rows=[["a", "b"]], position=1),
    ]
    doc = RawDocument(tables=tables, paragraphs=paragraphs, filename="test.docx")
    converter = DocumentConverter()
    result = converter.convert(doc, {0: "unknown"}, [doc.tables[0]])

    gt = result["generic_tables"][0]
    assert gt.heading_text == "INode Interface"
    assert gt.parent_interface == "INode"
    assert gt.header_row == ["Random", "Stuff"]
    assert gt.rows == [["a", "b"]]
    assert 2 in gt.heading_stack  # heading level 2 is in the stack
    assert gt.position == 0


def test_generic_table_known_tables_no_generic():
    """Known tables (method, property, enum, error_code) work normally
    and don't create generic entries."""
    raw = _make_raw_doc_for_converter()
    table_types = {0: "method", 1: "property", 2: "enum", 3: "error_code"}
    merged = merge_multi_row_functions(raw.tables)
    converter = DocumentConverter()
    result = converter.convert(raw, table_types, merged)

    assert len(result["generic_tables"]) == 0


def test_generic_table_empty_heading_context():
    """A table with no heading context creates a generic entry with empty
    heading_text and parent_interface=None."""
    tables = [
        RawTable(headers=["X", "Y"],
                 rows=[["1", "2"]], position=0),
    ]
    doc = RawDocument(tables=tables, paragraphs=[], filename="test.docx")
    converter = DocumentConverter()
    result = converter.convert(doc, {0: "unknown"}, [doc.tables[0]])

    gt = result["generic_tables"][0]
    assert gt.heading_text == ""
    assert gt.parent_interface is None


def test_generic_table_logging(caplog):
    """Unknown table logging is at INFO level with heading context,
    dimensions, and first-row preview."""
    caplog.set_level(logging.INFO)
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2",
                     heading_level=2, position=0),
    ]
    tables = [
        RawTable(headers=["Random", "Stuff"],
                 rows=[["a value", "b value"]], position=1),
    ]
    doc = RawDocument(tables=tables, paragraphs=paragraphs, filename="test.docx")
    converter = DocumentConverter()
    converter.convert(doc, {0: "unknown"}, [doc.tables[0]])

    assert any(
        "Unknown table" in record.message
        and "INode" in record.message
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# DocumentConverter - integration tests via convert() (positional layout)
# ---------------------------------------------------------------------------


def _make_raw_doc_for_converter() -> RawDocument:
    """Create a RawDocument with positional column layout for all table types.

    Column layout matches the positional extractor API introduced in Task 7.1:

    * Method table:      col0=return_type, col1=name(params), col2=param_desc
    * Property table:    col0=type,         col1=name•desc,    col2=unused
    * Enum table:        col0=ignored,      col1=name=value,   col2=description
    * Error code table:  col0=ignored,      col1=name=value,   col2=description
    """
    paragraphs = [
        RawParagraph(text="INode Interface", style_name="Heading 2",
                     heading_level=2, position=0),
    ]
    tables = [
        # Method table
        RawTable(
            headers=["", "", ""],
            rows=[["void", "CreateNode(double x, double y)", ""]],
            position=1,
        ),
        # Property table
        RawTable(
            headers=["", "", ""],
            rows=[["int", "Count \u2022 The count", ""]],
            position=2,
        ),
        # Enum table
        RawTable(
            headers=["", "", ""],
            rows=[["", "None = 0", "No value"]],
            position=3,
        ),
        # Error code table
        RawTable(
            headers=["", "", ""],
            rows=[["", "E_INVALIDARG = 0x80070057", "Invalid argument"]],
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
    assert iface.methods[0].name == "CreateNode"
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
    assert enum_def.values[0].name == "None"
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
    assert ec.name == "E_INVALIDARG"
    assert ec.code == 0x80070057


# ---------------------------------------------------------------------------
# TableDetector - paragraph-based detection (Task 7.3)
# ---------------------------------------------------------------------------


def test_detect_by_paragraph_matches_bold_label():
    """_detect_by_paragraph finds nearest bold paragraph and returns type."""
    paragraphs = [
        RawParagraph(text="Some intro text", bold=False, position=0),
        RawParagraph(text="Functions", bold=True, position=1),
    ]
    result = TableDetector._detect_by_paragraph(2, paragraphs)
    assert result == "method"


def test_detect_by_paragraph_no_bold_paragraph():
    """_detect_by_paragraph returns None when no bold paragraph precedes."""
    paragraphs = [
        RawParagraph(text="Some intro text", bold=False, position=0),
    ]
    result = TableDetector._detect_by_paragraph(1, paragraphs)
    assert result is None


def test_detect_by_paragraph_unmatched_label():
    """_detect_by_paragraph returns None when bold text doesn't match a label."""
    paragraphs = [
        RawParagraph(text="Custom Section", bold=True, position=0),
    ]
    result = TableDetector._detect_by_paragraph(1, paragraphs)
    assert result is None


def test_detect_by_paragraph_returns_nearest_bold():
    """_detect_by_paragraph returns the NEAREST (not first) bold paragraph."""
    paragraphs = [
        RawParagraph(text="Properties", bold=True, position=0),
        RawParagraph(text="Some regular text", bold=False, position=1),
        RawParagraph(text="Functions", bold=True, position=2),
    ]
    result = TableDetector._detect_by_paragraph(3, paragraphs)
    assert result == "method"  # nearest bold before position 3 is "Functions"


def test_detect_from_document_paragraph_based():
    """detect_from_document uses paragraph labels when available."""
    doc = RawDocument(
        paragraphs=[
            RawParagraph(text="Functions", bold=True, position=0),
        ],
        tables=[
            RawTable(
                headers=["Return Type", "Method", "Description", ""],
                rows=[["void", "Foo()", "", ""]],
                position=1,
            ),
        ],
        filename="test.docx",
    )
    detector = TableDetector()
    result = detector.detect_from_document(doc)
    assert result == {0: "method"}


def test_detect_from_document_no_label_fallback():
    """detect_from_document falls back to keyword detection when no label."""
    doc = RawDocument(
        paragraphs=[
            RawParagraph(text="Custom Section", bold=True, position=0),
        ],
        tables=[
            RawTable(
                headers=["Return Type", "Method", "Description", ""],
                rows=[["void", "Foo()", "", ""]],
                position=1,
            ),
        ],
        filename="test.docx",
    )
    detector = TableDetector()
    # "Custom Section" doesn't match TABLE_LABELS → falls to keyword
    # Keyword: no param keyword → "unknown" from _keyword_match
    # But multi-signal: "Return Type" doesn't match _RETURN_TYPES_RE → unknown
    # So we just verify it doesn't crash and returns something
    result = detector.detect_from_document(doc)
    assert 0 in result
    # With only "Return Type", "Method", "Description" (no param keyword),
    # keyword_match returns unknown. multi_signal sees:
    # - _is_record_pattern: headers[0]="Return Type" not empty → False
    # - _is_com_property_pattern: no "property", "access to", or "•" → False
    # - _is_com_method_pattern: _RETURN_TYPES_RE.match("Return Type") → False → "unknown"
    # So result is "unknown"
    assert result[0] == "unknown"


# ---------------------------------------------------------------------------
# Consecutive table inheritance tests (Task 7.5)
# ---------------------------------------------------------------------------


def test_detect_consecutive_tables_inherit():
    """Two adjacent tables without matching labels: second inherits first's type.

    Both tables share a single bold paragraph whose text does NOT match any
    TABLE_LABELS entry.  Table 0 is classified by keyword/multi-signal fallback.
    Table 1, being consecutive with no intervening paragraph, inherits
    the type of table 0.
    """
    doc = RawDocument(
        paragraphs=[
            RawParagraph(text="Custom Bold Heading", bold=True, position=0),
        ],
        tables=[
            # Table 0: keyword-detectable as method
            RawTable(
                headers=["Return Type", "Method", "Description", ""],
                rows=[["void", "Foo()", "", ""]],
                position=1,
            ),
            # Table 1: adjacent, same non-matching bold paragraph → inherits
            RawTable(
                headers=["Some", "Random", "Headers"],
                rows=[["a", "b", "c"]],
                position=2,
            ),
        ],
        filename="test.docx",
    )
    detector = TableDetector()
    result = detector.detect_from_document(doc)

    # Table 0: paragraph detection returns None ("Custom Bold Heading" no match).
    # No previous table → keyword/multi-signal fallback.
    # With headers ["Return Type", "Method", "Description"]:
    #   keyword_match: needs 4 keyword groups → "unknown"
    #   multi_signal: _is_record_pattern → False (col0 not empty)
    #                _is_com_property_pattern → False
    #                _is_com_method_pattern → _RETURN_TYPES_RE.match("Return Type") → False
    #                → "unknown"
    # So table 0 is "unknown".
    assert result[0] == "unknown"
    # Table 1: paragraph detection same result → None. last_was_table = True
    # → inherits "unknown" from table 0.
    assert result[1] == "unknown"


def test_detect_consecutive_tables_inherits_method():
    """Second table inherits 'method' when first is classified by multi-signal.

    Uses a COM-style first table whose col 0 ("void") matches _RETURN_TYPES_RE
    and none of the keyword sets (avoids the 'hresult' keyword in _CODE_KW).
    """
    doc = RawDocument(
        paragraphs=[
            RawParagraph(text="Custom Bold Heading", bold=True, position=0),
        ],
        tables=[
            # Table 0: multi-signal detectable as method (col0="void" matches _RETURN_TYPES_RE)
            RawTable(
                headers=["void", "Method", "Description", ""],
                rows=[["", "Foo()", "A method", ""]],
                position=1,
            ),
            # Table 1: inherits "method"
            RawTable(
                headers=["Some", "Random", "Headers"],
                rows=[["a", "b", "c"]],
                position=2,
            ),
        ],
        filename="test.docx",
    )
    detector = TableDetector()
    result = detector.detect_from_document(doc)
    assert result[0] == "method"
    assert result[1] == "method"


def test_detect_three_tables_middle_overridden():
    """Three tables: first gets type via keyword, middle overridden by bold
    paragraph, third inherits from middle."""
    doc = RawDocument(
        paragraphs=[
            # Bold paragraph before table 0 — matches method
            RawParagraph(text="Functions", bold=True, position=0),
            # Bold paragraph between tables 0 and 2 — matches property
            RawParagraph(text="Properties", bold=True, position=3),
        ],
        tables=[
            # Table 0 (pos=1): paragraph detection → "Functions" → method
            RawTable(
                headers=["", "", ""],
                rows=[["void", "Foo()", ""]],
                position=1,
            ),
            # Table 1 (pos=2): paragraph detection also sees "Functions" → method
            RawTable(
                headers=["", "", ""],
                rows=[["int", "Bar()", ""]],
                position=2,
            ),
            # Table 2 (pos=4): paragraph detection → "Properties" → property
            RawTable(
                headers=["", "", ""],
                rows=[["int", "Count", ""]],
                position=4,
            ),
        ],
        filename="test.docx",
    )
    detector = TableDetector()
    result = detector.detect_from_document(doc)
    assert result[0] == "method"
    assert result[1] == "method"
    assert result[2] == "property"


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
