"""Unit tests for boundary detectors (detection/boundaries.py)."""

import pytest
from src.pdf_semantic_chunking.extraction.model import DocumentElement, DocumentHierarchy
from src.pdf_semantic_chunking.enrichment.model import ComDocumentElement
from src.pdf_semantic_chunking.detection.boundaries import (
    HeadingBoundaryDetector,
    FunctionSignatureDetector,
    CodeBlockBoundaryDetector,
    TableBoundaryDetector,
    ContextPrefixBuilder,
    BoundaryDetector,
    BoundaryMarker,
)


# ======================================================================
# Helper factories
# ======================================================================


def _make_el(
    el_type: str,
    content: str = "",
    font_size: float = 0,
    children: list | None = None,
) -> DocumentElement:
    """Create a DocumentElement with optional font_size metadata."""
    el = DocumentElement(type=el_type, content=content)  # type: ignore[arg-type]
    el.metadata["font_size"] = font_size
    if children:
        el.children = children
    return el


def _make_com_el(
    com_type: str | None,
    content: str = "",
    element_name: str | None = None,
) -> ComDocumentElement:
    """Create a ComDocumentElement."""
    return ComDocumentElement(
        type="PARAGRAPH",  # type: ignore[arg-type]
        content=content,
        com_type=com_type,
        element_name=element_name,
    )


def _flat(els: list[DocumentElement]) -> list[DocumentElement]:
    """Wrap elements in a DocumentHierarchy and return flattened list."""
    root = DocumentElement(type="PAGE", content="")  # type: ignore[arg-type]
    root.children = els
    hier = DocumentHierarchy(root=root)
    return hier.flatten_depth_first()


# ======================================================================
# HeadingBoundaryDetector
# ======================================================================


class TestHeadingBoundaryDetector:
    """Tests for HeadingBoundaryDetector."""

    def test_h1_font_size_greater_than_18(self):
        detector = HeadingBoundaryDetector()
        els = [_make_el("HEADING", "Chapter 1", font_size=20)]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0] == (1, "heading", 90.0)

    def test_h2_font_size_greater_than_14(self):
        detector = HeadingBoundaryDetector()
        els = [_make_el("HEADING", "Section A", font_size=16)]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][1] == "heading"
        assert markers[0][2] == 80.0

    def test_markdown_h1_heading(self):
        detector = HeadingBoundaryDetector()
        els = [_make_el("HEADING", "# Introduction", font_size=12)]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 90.0

    def test_markdown_h2_heading(self):
        detector = HeadingBoundaryDetector()
        els = [_make_el("HEADING", "## Sub Section", font_size=12)]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 90.0

    def test_markdown_h3_is_not_h1_or_h2(self):
        detector = HeadingBoundaryDetector()
        els = [_make_el("HEADING", "### Sub Sub Section", font_size=12)]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 0

    def test_non_heading_element_no_marker(self):
        detector = HeadingBoundaryDetector()
        els = [_make_el("PARAGRAPH", "Just some text.", font_size=20)]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 0

    def test_small_font_no_marker(self):
        detector = HeadingBoundaryDetector()
        els = [_make_el("HEADING", "Small heading", font_size=10)]
        flat = _flat(els)
        markers = detector.detect(flat)
        # "Small heading" matches the new short-structural-line heuristic (priority 60.0)
        assert len(markers) == 1

    def test_multiple_headings_all_detected(self):
        detector = HeadingBoundaryDetector()
        els = [
            _make_el("HEADING", "# H1", font_size=12),
            _make_el("HEADING", "Large text", font_size=20),
            _make_el("HEADING", "Medium text", font_size=16),
        ]
        flat = _flat(els)
        markers = detector.detect(flat)
        # Content-based heuristics add an extra marker for "Medium text" (short structural line)
        assert len(markers) == 4

    def test_empty_content_heading_with_large_font(self):
        detector = HeadingBoundaryDetector()
        els = [_make_el("HEADING", "", font_size=20)]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1

    def test_font_size_14_not_h2(self):
        """font_size == 14 is NOT > 14, so no H2 marker."""
        detector = HeadingBoundaryDetector()
        els = [_make_el("HEADING", "Exactly 14", font_size=14)]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 0

    def test_font_size_18_detected_as_h2(self):
        """font_size == 18 is NOT > 18, but IS > 14, so H2 marker (80.0)."""
        detector = HeadingBoundaryDetector()
        els = [_make_el("HEADING", "Exactly 18", font_size=18)]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 80.0

    def test_heading_with_no_font_size_key(self):
        """Missing font_size key defaults to 0 via .get()."""
        detector = HeadingBoundaryDetector()
        el = DocumentElement(type="HEADING", content="No font")  # type: ignore[arg-type]
        els = [el]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 0


# ======================================================================
# FunctionSignatureDetector
# ======================================================================


class TestFunctionSignatureDetector:
    """Tests for FunctionSignatureDetector."""

    def test_com_return_type_long(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "long Foo(")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][1] == "function_signature"

    @pytest.mark.parametrize("return_type", [
        "void", "int", "bool", "double", "string", "ELongBoolean",
        "short", "byte", "float", "uint", "ulong", "HWND", "IntPtr",
        "object", "char", "decimal", "sbyte", "ushort", "SafeArray",
        "Array", "DateTime", "Guid", "Variant", "dynamic",
    ])
    def test_various_return_types_match(self, return_type):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", f"{return_type} MethodName(")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1, f"Return type '{return_type}' did not match"

    def test_com_import_attr_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "[ComImport]")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 100.0

    def test_guid_attr_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", '[Guid("1234-5678")]')]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 100.0

    def test_interface_type_attr_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 100.0

    def test_dll_import_attr_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", '[DllImport("user32.dll")]')]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 100.0

    def test_interface_declaration_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "interface IMyInterface")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 95.0

    def test_def_function_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "def my_function()")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 80.0

    def test_function_keyword_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "function doSomething()")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 80.0

    def test_class_declaration_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "class MyClass")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 80.0

    def test_public_access_modifier_matches(self):
        """Matches com_return_types first (void is a known return type), priority 90.0."""
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "public void DoSomething()")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        # "void DoSomething(" matches the return-type pattern at priority 90.0
        assert markers[0][2] == 90.0

    def test_private_access_modifier_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "private int _count()")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1

    def test_protected_access_modifier_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "protected string GetName()")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1

    def test_arrow_function_matches(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "x => x + 1")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1
        assert markers[0][2] == 60.0

    def test_plain_text_no_match(self):
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "This is just a plain sentence.")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 0

    def test_element_with_com_type_is_skipped(self):
        """Elements with a truthy com_type attribute should be skipped."""
        detector = FunctionSignatureDetector()
        el = _make_com_el(com_type="COM_METHOD", content="long Foo(", element_name="Foo")
        flat = _flat([el])
        markers = detector.detect(flat)
        assert len(markers) == 0

    def test_element_with_empty_com_type_not_skipped(self):
        """Elements with com_type='' should still be checked."""
        detector = FunctionSignatureDetector()
        el = _make_com_el(com_type="", content="long Foo(")
        flat = _flat([el])
        markers = detector.detect(flat)
        assert len(markers) == 1

    def test_element_with_none_com_type_not_skipped(self):
        """Elements with com_type=None should still be checked."""
        detector = FunctionSignatureDetector()
        el = _make_com_el(com_type=None, content="long Foo(")
        flat = _flat([el])
        markers = detector.detect(flat)
        assert len(markers) == 1

    def test_first_match_wins_no_duplicates(self):
        """Only one marker per element (break after first match)."""
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "long Foo( interface IName")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1

    def test_e_result_type_matches(self):
        """EResult types like E_UNEXPECTEDResult should match the return-type pattern."""
        detector = FunctionSignatureDetector()
        els = [_make_el("PARAGRAPH", "E_UNEXPECTEDResult CheckStatus(")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 1


# ======================================================================
# CodeBlockBoundaryDetector
# ======================================================================


class TestCodeBlockBoundaryDetector:
    """Tests for CodeBlockBoundaryDetector."""

    def test_code_block_start_and_end_markers(self):
        detector = CodeBlockBoundaryDetector()
        els = [
            _make_el("PARAGRAPH", "text before"),
            _make_el("CODE_BLOCK", "code here"),
            _make_el("PARAGRAPH", "text after"),
        ]
        flat = _flat(els)
        markers = detector.detect(flat)
        # flat = [PAGE(0), PARAGRAPH(1), CODE_BLOCK(2), PARAGRAPH(3)]
        assert (2, "code_block_start", 70.0) in markers
        assert (3, "code_block_end", 70.0) in markers

    def test_inferred_code_block(self):
        detector = CodeBlockBoundaryDetector()
        els = [
            _make_el("INFERRED_CODE_BLOCK", "inferred"),
            _make_el("PARAGRAPH", "after"),
        ]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert (1, "code_block_start", 70.0) in markers
        assert (2, "code_block_end", 70.0) in markers

    def test_last_element_end_at_same_index(self):
        detector = CodeBlockBoundaryDetector()
        els = [_make_el("CODE_BLOCK", "only code")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert (1, "code_block_start", 70.0) in markers
        assert (1, "code_block_end", 70.0) in markers

    def test_non_code_elements_no_markers(self):
        detector = CodeBlockBoundaryDetector()
        els = [
            _make_el("PARAGRAPH", "p1"),
            _make_el("HEADING", "h1"),
            _make_el("TABLE", "t1"),
        ]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 0

    def test_multiple_code_blocks(self):
        detector = CodeBlockBoundaryDetector()
        els = [
            _make_el("CODE_BLOCK", "block1"),
            _make_el("PARAGRAPH", "gap"),
            _make_el("CODE_BLOCK", "block2"),
        ]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 4

    def test_adjacent_code_blocks(self):
        detector = CodeBlockBoundaryDetector()
        els = [
            _make_el("CODE_BLOCK", "block1"),
            _make_el("CODE_BLOCK", "block2"),
        ]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert (1, "code_block_start", 70.0) in markers
        assert (2, "code_block_end", 70.0) in markers
        assert (2, "code_block_start", 70.0) in markers


# ======================================================================
# TableBoundaryDetector
# ======================================================================


class TestTableBoundaryDetector:
    """Tests for TableBoundaryDetector."""

    def test_table_start_and_end_markers(self):
        detector = TableBoundaryDetector()
        els = [
            _make_el("PARAGRAPH", "before"),
            _make_el("TABLE", "table data"),
            _make_el("PARAGRAPH", "after"),
        ]
        flat = _flat(els)
        markers = detector.detect(flat)
        # flat = [PAGE(0), PARAGRAPH(1), TABLE(2), PARAGRAPH(3)]
        assert (2, "table_start", 70.0) in markers
        assert (3, "table_end", 70.0) in markers

    def test_inferred_table(self):
        detector = TableBoundaryDetector()
        els = [
            _make_el("INFERRED_TABLE", "inferred"),
            _make_el("PARAGRAPH", "after"),
        ]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert (1, "table_start", 70.0) in markers
        assert (2, "table_end", 70.0) in markers

    def test_last_element_end_at_same_index(self):
        detector = TableBoundaryDetector()
        els = [_make_el("TABLE", "only table")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert (1, "table_start", 70.0) in markers
        assert (1, "table_end", 70.0) in markers

    def test_non_table_elements_no_markers(self):
        detector = TableBoundaryDetector()
        els = [_make_el("PARAGRAPH", "just text")]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 0

    def test_multiple_tables(self):
        detector = TableBoundaryDetector()
        els = [
            _make_el("TABLE", "t1"),
            _make_el("PARAGRAPH", "gap"),
            _make_el("TABLE", "t2"),
        ]
        flat = _flat(els)
        markers = detector.detect(flat)
        assert len(markers) == 4


# ======================================================================
# ContextPrefixBuilder
# ======================================================================


class TestContextPrefixBuilder:
    """Tests for ContextPrefixBuilder."""

    def test_all_three_parts(self):
        builder = ContextPrefixBuilder()
        result = builder.build("IMyInterface", "Methods", "Foo")
        assert result == "Interface: IMyInterface | Section: Methods | Element: Foo"

    def test_only_interface(self):
        builder = ContextPrefixBuilder()
        result = builder.build("IMyInterface", None, None)
        assert result == "Interface: IMyInterface"

    def test_only_section(self):
        builder = ContextPrefixBuilder()
        result = builder.build(None, "Properties", None)
        assert result == "Section: Properties"

    def test_only_element_name(self):
        builder = ContextPrefixBuilder()
        result = builder.build(None, None, "Bar")
        assert result == "Element: Bar"

    def test_all_none_returns_empty(self):
        builder = ContextPrefixBuilder()
        result = builder.build(None, None, None)
        assert result == ""

    def test_interface_and_element_only(self):
        builder = ContextPrefixBuilder()
        result = builder.build("IFoo", None, "GetData")
        assert result == "Interface: IFoo | Element: GetData"

    def test_empty_strings_treated_as_falsy(self):
        """Empty strings are falsy so they are skipped, same as None."""
        builder = ContextPrefixBuilder()
        result = builder.build("", "", "")
        assert result == ""


# ======================================================================
# BoundaryDetector (integration of sub-detectors)
# ======================================================================


class TestBoundaryDetector:
    """Tests for BoundaryDetector that orchestrates all sub-detectors."""

    def _hierarchy_from_els(self, els: list[DocumentElement]) -> DocumentHierarchy:
        root = DocumentElement(type="PAGE", content="")  # type: ignore[arg-type]
        root.children = els
        return DocumentHierarchy(root=root)

    def test_uses_all_sub_detectors(self):
        detector = BoundaryDetector()
        els = [
            _make_el("HEADING", "Large Title", font_size=20),
            _make_el("PARAGRAPH", "long Foo("),
            _make_el("CODE_BLOCK", "code"),
            _make_el("TABLE", "data"),
            _make_el("PARAGRAPH", "plain text"),
        ]
        hierarchy = self._hierarchy_from_els(els)
        indices = detector.detect(hierarchy)
        # flat = [PAGE(0), HEADING(1), PARAGRAPH(2), CODE_BLOCK(3), TABLE(4), PARAGRAPH(5)]
        assert 1 in indices  # heading
        assert 2 in indices  # func sig
        assert 3 in indices  # code block
        assert 4 in indices  # table start or code_block_end
        assert 5 in indices  # table_end (end marker at next element after table)

    def test_deduplicates_overlapping_boundary_indices(self):
        detector = BoundaryDetector()
        els = [
            _make_el("HEADING", "int Foo(", font_size=20),
        ]
        hierarchy = self._hierarchy_from_els(els)
        indices = detector.detect(hierarchy)
        assert indices == [1]

    def test_returns_sorted_unique_indices(self):
        detector = BoundaryDetector()
        els = [
            _make_el("PARAGRAPH", "plain"),
            _make_el("HEADING", "Title", font_size=20),
            _make_el("PARAGRAPH", "plain"),
            _make_el("TABLE", "data"),
            _make_el("PARAGRAPH", "plain"),
        ]
        hierarchy = self._hierarchy_from_els(els)
        indices = detector.detect(hierarchy)
        assert indices == sorted(set(indices))
        # flat = [PAGE(0), PARAGRAPH(1), HEADING(2), PARAGRAPH(3), TABLE(4), PARAGRAPH(5)]
        # Boundaries: heading(2), table_start(4), table_end(5) -> [2, 4, 5]
        assert len(indices) == 3

    def test_register_custom_detector(self):
        detector = BoundaryDetector()

        def custom_detector(flat: list) -> list[BoundaryMarker]:
            return [(2, "custom", 50.0)]

        detector.register_detector(custom_detector)
        els = [_make_el("PARAGRAPH", "a"), _make_el("PARAGRAPH", "b")]
        hierarchy = self._hierarchy_from_els(els)
        indices = detector.detect(hierarchy)
        assert 2 in indices

    def test_handles_detector_exception_gracefully(self):
        detector = BoundaryDetector()

        def broken_detector(flat: list) -> list[BoundaryMarker]:
            raise RuntimeError("Something went wrong")

        detector.register_detector(broken_detector)
        els = [_make_el("HEADING", "Title", font_size=20)]
        hierarchy = self._hierarchy_from_els(els)
        indices = detector.detect(hierarchy)
        assert isinstance(indices, list)
        assert 1 in indices  # heading still detected

    def test_com_priority_ordering(self):
        """COM priority: function > property > enum > record > error_code."""
        detector = BoundaryDetector()

        def com_detector(flat: list) -> list[BoundaryMarker]:
            return [
                (1, "error_code", 60.0),
                (1, "property", 90.0),
                (1, "function", 100.0),
                (1, "enum", 80.0),
                (1, "record", 70.0),
            ]

        detector.register_detector(com_detector)
        els = [_make_el("PARAGRAPH", "a")]
        hierarchy = self._hierarchy_from_els(els)
        indices = detector.detect(hierarchy)
        assert isinstance(indices, list)
        # should be deduplicated to just 1
        assert indices == [1]

    def test_empty_hierarchy_returns_empty(self):
        detector = BoundaryDetector()
        hierarchy = DocumentHierarchy()
        indices = detector.detect(hierarchy)
        assert indices == []

    def test_no_boundaries_returns_empty(self):
        detector = BoundaryDetector()
        els = [_make_el("PARAGRAPH", "plain")]
        hierarchy = self._hierarchy_from_els(els)
        indices = detector.detect(hierarchy)
        assert indices == []
