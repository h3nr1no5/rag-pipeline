"""Unit tests for the augmentation module.

Tests for ``build_augmented_text`` covering COM API prefixes,
section hierarchy prefixes, element type prefixes, and edge cases.
"""


from src.pdf_semantic_chunking.augmentation import build_augmented_text


class TestBuildAugmentedText:
    """Tests for :func:`build_augmented_text`."""

    # ------------------------------------------------------------------
    # COM API element type prefixes — happy paths
    # ------------------------------------------------------------------

    def test_com_function(self):
        """COM function with interface + element_name gets 'COM API Function: I.Name' prefix."""
        content = "HRESULT SomeMethod(int param);"
        metadata = {
            "element_type": "function",
            "interface": "IInterface",
            "element_name": "SomeMethod",
        }
        result = build_augmented_text(content, metadata)

        assert result.startswith("COM API Function: IInterface.SomeMethod")
        assert "Interface: IInterface" in result
        assert "Element Name: SomeMethod" in result
        assert content in result

    def test_com_property(self):
        """COM property gets 'COM API Property' prefix."""
        content = "Gets or sets the active document."
        metadata = {
            "element_type": "property",
            "interface": "IDispatch",
            "element_name": "ActiveDocument",
        }
        result = build_augmented_text(content, metadata)

        assert result.startswith("COM API Property: IDispatch.ActiveDocument")

    def test_com_enum(self):
        """COM enum gets 'COM API Enum' prefix."""
        content = "WdAlertLevel enum values."
        metadata = {
            "element_type": "enum",
            "interface": "IEnums",
            "element_name": "WdAlertLevel",
        }
        result = build_augmented_text(content, metadata)

        assert result.startswith("COM API Enum: IEnums.WdAlertLevel")

    def test_com_record(self):
        """COM record gets 'COM API Record' prefix."""
        content = "STRUCT fields."
        metadata = {
            "element_type": "record",
            "interface": "IRecords",
            "element_name": "MyRecord",
        }
        result = build_augmented_text(content, metadata)

        assert result.startswith("COM API Record: IRecords.MyRecord")

    def test_com_error_code(self):
        """COM error_code gets 'COM API Error Code' prefix (multi-word type)."""
        content = "The operation completed successfully."
        metadata = {
            "element_type": "error_code",
            "interface": "IErrors",
            "element_name": "S_OK",
        }
        result = build_augmented_text(content, metadata)

        assert result.startswith("COM API Error Code: IErrors.S_OK")

    # ------------------------------------------------------------------
    # COM element without interface / element_name — falls through
    # ------------------------------------------------------------------

    def test_com_element_without_interface_falls_through(self):
        """COM type without ``interface`` skips COM block and uses element_type prefix."""
        metadata = {
            "element_type": "function",
            "element_name": "SomeMethod",
        }
        result = build_augmented_text("content", metadata)

        assert result == "[function]\ncontent"

    def test_com_element_without_element_name_falls_through(self):
        """COM type without ``element_name`` skips COM block and uses element_type prefix."""
        metadata = {
            "element_type": "property",
            "interface": "IFoo",
        }
        result = build_augmented_text("content", metadata)

        assert result == "[property]\ncontent"

    # ------------------------------------------------------------------
    # Section hierarchy
    # ------------------------------------------------------------------

    def test_section_hierarchy_multi_level(self):
        """Multi-level ``section_hierarchy`` renders as ``[Section: A > B > C]``."""
        content = "Nested section text."
        metadata = {"section_hierarchy": ["A", "B", "C"]}
        result = build_augmented_text(content, metadata)

        assert result == "[Section: A > B > C]\n" + content

    def test_section_hierarchy_single_level(self):
        """Single-level ``section_hierarchy`` renders as ``[Section: A]``."""
        content = "Top-level section text."
        metadata = {"section_hierarchy": ["Top"]}
        result = build_augmented_text(content, metadata)

        assert result == "[Section: Top]\n" + content

    def test_section_hierarchy_takes_precedence_over_element_type(self):
        """When both section_hierarchy and element_type are present, section wins."""
        content = "Section content."
        metadata = {
            "section_hierarchy": ["Config"],
            "element_type": "description",
        }
        result = build_augmented_text(content, metadata)

        assert result.startswith("[Section: Config]")

    # ------------------------------------------------------------------
    # Element type only (no COM match, no section)
    # ------------------------------------------------------------------

    def test_element_type_only(self):
        """Only ``element_type`` present prefixes content with ``[type]``."""
        content = "Descriptive text."
        metadata = {"element_type": "description"}
        result = build_augmented_text(content, metadata)

        assert result == "[description]\n" + content

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_no_metadata_returns_raw_content(self):
        """Empty metadata dict returns ``chunk_content`` unchanged."""
        content = "Raw text with no metadata."
        result = build_augmented_text(content, {})

        assert result == content

    def test_empty_content_with_element_type(self):
        """Empty content with element_type returns just the bracketed prefix."""
        result = build_augmented_text("", {"element_type": "description"})

        assert result == "[description]\n"

    def test_empty_content_no_metadata(self):
        """Empty content with no metadata returns an empty string."""
        result = build_augmented_text("", {})

        assert result == ""
