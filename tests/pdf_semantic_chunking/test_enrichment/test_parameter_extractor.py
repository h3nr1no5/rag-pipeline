"""Tests for src.pdf_semantic_chunking.enrichment.parameter_extractor.ParameterExtractor.

Covers extract_from_signature, associate_descriptions, extract_from_bullet_list,
and the internal helpers _split_params and _parse_single_param.
"""

import pytest

from src.pdf_semantic_chunking.enrichment.model import ComDocumentElement
from src.pdf_semantic_chunking.enrichment.parameter_extractor import ParameterExtractor


@pytest.fixture
def extractor() -> ParameterExtractor:
    return ParameterExtractor()


# ============================ extract_from_signature ===========================
class TestExtractFromSignature:
    def test_single_in_param(self, extractor: ParameterExtractor) -> None:
        result = extractor.extract_from_signature("long BringToFront([In] int nHwnd)")
        assert result == [
            {"name": "nHwnd", "direction": "in", "type": "int", "description": None},
        ]

    def test_no_direction_attribute(self, extractor: ParameterExtractor) -> None:
        result = extractor.extract_from_signature("int Foo(int x)")
        assert result == [
            {"name": "x", "direction": "in", "type": "int", "description": None},
        ]

    def test_multiple_params(self, extractor: ParameterExtractor) -> None:
        result = extractor.extract_from_signature(
            "long SetValues([In] int first, [Out] int second)"
        )
        assert result == [
            {"name": "first", "direction": "in", "type": "int", "description": None},
            {"name": "second", "direction": "out", "type": "int", "description": None},
        ]

    def test_out_keyword_confuses_type_parsing(self, extractor: ParameterExtractor) -> None:
        """When the signature uses 'out' keyword before the type (e.g. 'out int'),
        the parser treats 'out' as the type and 'int' as the name (known limitation)."""
        result = extractor.extract_from_signature(
            "long SetValues([In] int first, [Out] out int second)"
        )
        assert result == [
            {"name": "first", "direction": "in", "type": "int", "description": None},
            {"name": "int", "direction": "out", "type": "out", "description": None},
        ]

    def test_marshal_as_skipped_direction_defaults_to_in(self, extractor: ParameterExtractor) -> None:  # noqa: E501
        """[Out, MarshalAs(...)] is not recognized as a direction attribute,
        so direction defaults to 'in'. However type/name after the attribute
        are still extracted."""
        result = extractor.extract_from_signature(
            "long get_ActiveModel([Out, MarshalAs(UnmanagedType.Interface)] out IAxisVMModel ppModel)"  # noqa: E501
        )
        assert result == [
            {"name": "IAxisVMModel", "direction": "in", "type": "out", "description": None},
        ]

    def test_in_out_direction_comma_splits_bracket(self, extractor: ParameterExtractor) -> None:
        """Known limitation: _split_params splits on all commas at depth 0,
        including commas inside [In, Out] brackets, so the direction prefix
        gets split and the direction metadata is lost."""
        result = extractor.extract_from_signature(
            "long Foo([In, Out] int value)"
        )
        # [In, Out] is split at the comma → only "Out] int value" is parsed,
        # direction defaults to "in"
        assert result == [
            {"name": "value", "direction": "in", "type": "int", "description": None},
        ]

    def test_in_out_with_ref_keyword(self, extractor: ParameterExtractor) -> None:
        """ref keyword is treated as type (known limitation).
        Direction is also lost due to comma-in-bracket splitting."""
        result = extractor.extract_from_signature(
            "long Foo([In, Out] ref int value)"
        )
        assert result == [
            {"name": "int", "direction": "in", "type": "ref", "description": None},
        ]

    def test_marshal_as_in_prefix(self, extractor: ParameterExtractor) -> None:
        """[In, MarshalAs(...)] is skipped, direction defaults to 'in',
        but type/name are still extracted."""
        result = extractor.extract_from_signature(
            "long OpenModel([In, MarshalAs(UnmanagedType.BStr)] string bstrFileName)"
        )
        assert result == [
            {"name": "bstrFileName", "direction": "in", "type": "string", "description": None},
        ]

    def test_no_params(self, extractor: ParameterExtractor) -> None:
        result = extractor.extract_from_signature("void Foo()")
        assert result == []

    def test_empty_string(self, extractor: ParameterExtractor) -> None:
        result = extractor.extract_from_signature("")
        assert result == []

    def test_no_parens(self, extractor: ParameterExtractor) -> None:
        result = extractor.extract_from_signature("int x")
        assert result == []

    def test_param_with_default(self, extractor: ParameterExtractor) -> None:
        result = extractor.extract_from_signature("void Foo(int x = 42)")
        assert result == [
            {"name": "x", "direction": "in", "type": "int", "description": None},
        ]

    def test_nested_generic_param(self, extractor: ParameterExtractor) -> None:
        result = extractor.extract_from_signature(
            "long Process([In] Dictionary<string, int> mapping)"
        )
        assert result == [
            {"name": "mapping", "direction": "in", "type": "Dictionary<string, int>", "description": None},  # noqa: E501
        ]


# ================================= _split_params ===============================
class TestSplitParams:
    def test_simple_split(self, extractor: ParameterExtractor) -> None:
        parts = extractor._split_params("int a, string b, bool c")
        assert parts == ["int a", "string b", "bool c"]

    def test_nested_generics(self, extractor: ParameterExtractor) -> None:
        parts = extractor._split_params("Dictionary<string, int> mapping, int value")
        assert parts == ["Dictionary<string, int> mapping", "int value"]

    def test_deeply_nested(self, extractor: ParameterExtractor) -> None:
        parts = extractor._split_params(
            "Dictionary<string, List<int>> items, KeyValuePair<int, bool> pair"
        )
        assert parts == ["Dictionary<string, List<int>> items", "KeyValuePair<int, bool> pair"]

    def test_single_param(self, extractor: ParameterExtractor) -> None:
        parts = extractor._split_params("[In] int nHwnd")
        assert parts == ["[In] int nHwnd"]

    def test_trailing_comma_no_empty_part(self, extractor: ParameterExtractor) -> None:
        """A trailing comma results in a trailing space that is stripped
        and not added as an empty part."""
        parts = extractor._split_params("int a, int b, ")
        assert parts == ["int a", "int b"]


# ================================ _parse_single_param ==========================
class TestParseSingleParam:
    def test_simple_in(self, extractor: ParameterExtractor) -> None:
        result = extractor._parse_single_param("[In] int nHwnd")
        assert result == {
            "name": "nHwnd", "direction": "in", "type": "int", "description": None,
        }

    def test_in_out_direction(self, extractor: ParameterExtractor) -> None:
        result = extractor._parse_single_param("[In, Out] int value")
        assert result == {
            "name": "value", "direction": "in,out", "type": "int", "description": None,
        }

    def test_in_out_with_ref(self, extractor: ParameterExtractor) -> None:
        """ref keyword is treated as the type (known limitation)."""
        result = extractor._parse_single_param("[In, Out] ref int value")
        assert result == {
            "name": "int", "direction": "in,out", "type": "ref", "description": None,
        }

    def test_out_with_keyword(self, extractor: ParameterExtractor) -> None:
        """out keyword before the type is treated as the type."""
        result = extractor._parse_single_param("[Out] out IAxisVMModel ppModel")
        assert result == {
            "name": "IAxisVMModel", "direction": "out", "type": "out", "description": None,
        }

    def test_no_direction(self, extractor: ParameterExtractor) -> None:
        result = extractor._parse_single_param("int x")
        assert result == {
            "name": "x", "direction": "in", "type": "int", "description": None,
        }

    def test_array_type(self, extractor: ParameterExtractor) -> None:
        result = extractor._parse_single_param("[In] byte[] buffer")
        assert result["type"] == "byte[]"
        assert result["name"] == "buffer"

    def test_generic_type(self, extractor: ParameterExtractor) -> None:
        result = extractor._parse_single_param("Dictionary<string, int> mapping")
        assert result["type"] == "Dictionary<string, int>"
        assert result["name"] == "mapping"

    def test_marshal_as_skipped_name_extracted(self, extractor: ParameterExtractor) -> None:
        """Composite attribute [In, MarshalAs(...)] is not matched by
        PARAM_DIRECTION_PATTERN, but the type/name after it are still parsed."""
        result = extractor._parse_single_param(
            "[In, MarshalAs(UnmanagedType.BStr)] string bstrFileName"
        )
        assert result == {
            "name": "bstrFileName",
            "direction": "in",
            "type": "string",
            "description": None,
        }

    def test_empty_returns_none(self, extractor: ParameterExtractor) -> None:
        assert extractor._parse_single_param("") is None


# ============================== associate_descriptions =========================
class TestAssociateDescriptions:
    def test_matching_descriptions(self, extractor: ParameterExtractor) -> None:
        params = [
            {"name": "nHwnd", "direction": "in", "type": "int", "description": None},
            {"name": "bVisible", "direction": "in", "type": "bool", "description": None},
        ]
        desc_text = (
            "nHwnd: Handle to the parent window.\n"
            "bVisible: Whether the window is visible."
        )
        result = extractor.associate_descriptions(params, desc_text)
        assert result[0]["description"] == "Handle to the parent window."
        assert result[1]["description"] == "Whether the window is visible."

    def test_matching_with_dash_bullets(self, extractor: ParameterExtractor) -> None:
        params = [
            {"name": "x", "direction": "in", "type": "int", "description": None},
        ]
        desc_text = "- x: The X coordinate."
        result = extractor.associate_descriptions(params, desc_text)
        assert result[0]["description"] == "The X coordinate."

    def test_matching_with_star_bullets(self, extractor: ParameterExtractor) -> None:
        params = [
            {"name": "name", "direction": "in", "type": "string", "description": None},
        ]
        desc_text = "* name - The element name."
        result = extractor.associate_descriptions(params, desc_text)
        assert result[0]["description"] == "The element name."

    def test_no_match_leaves_unchanged(self, extractor: ParameterExtractor) -> None:
        params = [
            {"name": "nHwnd", "direction": "in", "type": "int", "description": None},
        ]
        desc_text = "Some other text that does not match."
        result = extractor.associate_descriptions(params, desc_text)
        assert result[0]["description"] is None

    def test_line_startswith_param_name(self, extractor: ParameterExtractor) -> None:
        """associate_descriptions checks if the line starts with the param name
        (case-insensitive). A line like 'nHwndHandle: The handle.' DOES start
        with 'nHwnd' (string prefix match) so it will be matched."""
        params = [
            {"name": "nHwnd", "direction": "in", "type": "int", "description": None},
        ]
        # 'nHwndHandle: The handle.' starts with 'nHwnd' → matches!
        desc_text = "nHwndHandle: The handle."
        result = extractor.associate_descriptions(params, desc_text)
        assert result[0]["description"] == "Handle: The handle."

    def test_line_does_not_start_with_param_name(self, extractor: ParameterExtractor) -> None:
        """If the line text does not start with the param name, no match."""
        params = [
            {"name": "nHwnd", "direction": "in", "type": "int", "description": None},
        ]
        desc_text = "Handle to the parent window."
        result = extractor.associate_descriptions(params, desc_text)
        assert result[0]["description"] is None

    def test_partial_line_matches_exact_param_name(self, extractor: ParameterExtractor) -> None:
        """A line that starts with the exact param name gets the rest as description."""
        params = [
            {"name": "nHwnd", "direction": "in", "type": "int", "description": None},
        ]
        desc_text = "nHwnd Handle to the parent window"
        result = extractor.associate_descriptions(params, desc_text)
        assert result[0]["description"] == "Handle to the parent window"

    def test_empty_description_text_returns_unchanged(self, extractor: ParameterExtractor) -> None:
        params = [
            {"name": "x", "direction": "in", "type": "int", "description": None},
        ]
        result = extractor.associate_descriptions(params, "")
        assert result == params

    def test_empty_params_returns_unchanged(self, extractor: ParameterExtractor) -> None:
        result = extractor.associate_descriptions([], "nHwnd: handle")
        assert result == []


# ============================= extract_from_bullet_list ========================
class TestExtractFromBulletList:
    def test_bullet_list_simple(self, extractor: ParameterExtractor) -> None:
        el = ComDocumentElement(
            type="LIST",
            content=(
                "- int nHwnd Handle to the parent window\n"
                "- bool bVisible Visibility flag\n"
                "- string name The element name"
            ),
        )
        result = extractor.extract_from_bullet_list(el)
        assert len(result) == 3
        assert result[0] == {
            "name": "nHwnd", "direction": "in", "type": "int", "description": "Handle to the parent window",  # noqa: E501
        }
        assert result[1] == {
            "name": "bVisible", "direction": "in", "type": "bool", "description": "Visibility flag",
        }
        assert result[2] == {
            "name": "name", "direction": "in", "type": "string", "description": "The element name",
        }

    def test_star_bullets(self, extractor: ParameterExtractor) -> None:
        el = ComDocumentElement(
            type="LIST",
            content="* int id The identifier\n* string label The display label",
        )
        result = extractor.extract_from_bullet_list(el)
        assert len(result) == 2
        assert result[0]["name"] == "id"
        assert result[1]["name"] == "label"

    def test_no_bullets(self, extractor: ParameterExtractor) -> None:
        el = ComDocumentElement(type="PARAGRAPH", content="This is not a bullet list.")
        result = extractor.extract_from_bullet_list(el)
        assert result == []

    def test_empty_content(self, extractor: ParameterExtractor) -> None:
        el = ComDocumentElement(type="LIST", content="")
        result = extractor.extract_from_bullet_list(el)
        assert result == []

    def test_generic_type_in_bullet(self, extractor: ParameterExtractor) -> None:
        el = ComDocumentElement(
            type="LIST",
            content="- Dictionary<string, int> mapping The key-value mapping",
        )
        result = extractor.extract_from_bullet_list(el)
        assert result == [
            {"name": "mapping", "direction": "in", "type": "Dictionary<string, int>", "description": "The key-value mapping"},  # noqa: E501
        ]

    def test_description_eats_following_lines_due_to_s_pattern(self, extractor: ParameterExtractor) -> None:  # noqa: E501
        """Known limitation: the ``\\s*`` before ``(.*)`` greedily consumes newlines,
        so description for the first bullet captures subsequent content."""
        el = ComDocumentElement(
            type="LIST",
            content="- int count\n- string text",
        )
        result = extractor.extract_from_bullet_list(el)
        assert len(result) == 1
        # The first (and only) match: \s* before (.*) eats the \n, then (.*) captures the rest
        assert result[0]["name"] == "count"
        assert result[0]["type"] == "int"
        assert result[0]["description"] == "- string text"
