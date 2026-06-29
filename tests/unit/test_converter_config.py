"""Unit tests for DocumentConverter configurable features.

Task 9.7 — Converter config application (heading_policy, type_patterns, etc.)
Task 9.8 — Record table parsing (_convert_record_table)
Task 9.9 — Type_patterns matching
Task 9.10 — Parent_interface assignment for enums and error_codes

Updated for Task 7.2: Positional column layout; type_patterns are compiled re.Pattern.
"""

import re

from src.domain.rag.api_docs.extraction.converter import DocumentConverter
from src.domain.rag.api_docs.extraction.docx_parser import (
    RawDocument,
    RawParagraph,
    RawTable,
)

# ── Shared test helpers ──────────────────────────────────────────────────


def _make_empty_converter(config: dict | None = None) -> DocumentConverter:
    """Return a DocumentConverter with optional config pre-applied."""
    converter = DocumentConverter()
    if config:
        converter._apply_config(config)
    return converter


# ---------------------------------------------------------------------------
# Task 9.7 — Converter config application
# ---------------------------------------------------------------------------


class TestConverterConfig:
    def test_default_config_values(self):
        """Converter has sensible defaults before any config is applied."""
        converter = DocumentConverter()
        assert converter.heading_policy["interface_depth"] == 2
        # type_patterns values are compiled re.Pattern objects
        assert isinstance(converter.type_patterns["enum"], re.Pattern)
        assert converter.type_patterns["enum"].pattern == r"^(enums|enum)$"
        assert converter.type_patterns["enum"].flags & re.IGNORECASE
        assert converter.max_depth == 5
        assert converter.format_style == "detailed"
        assert converter.include_signatures is True
        assert converter.include_descriptions is True
        assert converter.min_chunk_length == 50

    def test_apply_heading_policy(self):
        """heading_policy config overrides defaults."""
        converter = _make_empty_converter(
            {"heading_policy": {"interface_depth": 1, "method_depth": 2}}
        )
        assert converter.heading_policy["interface_depth"] == 1
        assert converter.heading_policy["method_depth"] == 2
        # Unchanged defaults remain
        assert converter.heading_policy["enum_depth"] == 2

    def test_apply_type_patterns(self):
        """type_patterns config overrides specified keys."""
        converter = _make_empty_converter(
            {"type_patterns": {"record": r"^(mymodel)$"}}
        )
        # Updated pattern is a compiled re.Pattern
        assert isinstance(converter.type_patterns["record"], re.Pattern)
        assert converter.type_patterns["record"].search("MyModel")
        # Other patterns unchanged
        assert converter.type_patterns["enum"].search("Enums")

    def test_apply_scalar_configs(self):
        """max_depth, format_style, include_*, min_chunk_length are applied."""
        converter = _make_empty_converter(
            {
                "max_depth": 3,
                "format_style": "compact",
                "include_signatures": False,
                "include_descriptions": False,
                "min_chunk_length": 10,
            }
        )
        assert converter.max_depth == 3
        assert converter.format_style == "compact"
        assert converter.include_signatures is False
        assert converter.include_descriptions is False
        assert converter.min_chunk_length == 10

    def test_convert_passes_config_through(self):
        """convert() applies config when passed as parameter."""
        raw = RawDocument(
            paragraphs=[
                RawParagraph(text="INode Interface", heading_level=2, position=0),
            ],
            tables=[
                RawTable(
                    headers=["", "", ""],
                    rows=[["void", "Create(double x)", ""]],
                    position=1,
                ),
            ],
            filename="test.docx",
        )
        table_types = {0: "method"}
        merged = raw.tables

        # Without config — uses defaults
        converter = DocumentConverter()
        result = converter.convert(raw, table_types, merged)
        assert result["interfaces"][0].methods[0].return_type == "void"

        # With config — doesn't crash and is applied
        converter2 = DocumentConverter()
        converter2.convert(
            raw, table_types, merged,
            config={"format_style": "compact", "max_depth": 2},
        )
        # Verify the config was picked up
        assert converter2.format_style == "compact"
        assert converter2.max_depth == 2

    def test_empty_config_does_not_change_defaults(self):
        """Empty config dict leaves all defaults intact."""
        converter = _make_empty_converter({})
        assert converter.max_depth == 5
        assert converter.format_style == "detailed"


# ---------------------------------------------------------------------------
# Task 9.8 — Record table parsing (updated for positional layout)
# ---------------------------------------------------------------------------


class TestConverterRecordTable:
    def test_convert_record_table_basic(self):
        """_convert_record_table creates APIRecord with fields (positional layout)."""
        converter = DocumentConverter()
        # Use empty headers so the header row doesn't create a spurious field
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

    def test_convert_record_table_no_fields(self):
        """Table with no valid fields (empty rows) returns None."""
        converter = DocumentConverter()
        RawTable(
            headers=["Type", "Name"],
            rows=[],
        )
        # Only the header row is processed. Header row has col0="Type" which
        # is non-empty, so it would create a field from the header text.
        # Use empty headers to get no fields.
        table_empty = RawTable(headers=["", ""], rows=[])
        record = converter._convert_record_table(table_empty)
        assert record is None

    def test_convert_record_table_unknown_caption(self):
        """Missing caption defaults to UnknownRecord."""
        converter = DocumentConverter()
        table = RawTable(
            headers=["Type", "Name", "Description"],
            rows=[["int", "Id", "Identifier"]],
        )
        record = converter._convert_record_table(table)
        assert record is not None
        assert record.name == "UnknownRecord"

    def test_convert_integration_with_config(self):
        """Record tables are processed during convert() when table_type is 'record'."""
        raw = RawDocument(
            paragraphs=[
                RawParagraph(text="Records", heading_level=2, position=0),
            ],
            tables=[
                RawTable(
                    headers=["", "", ""],
                    rows=[["int", "X", "Coordinate"]],
                    position=1,
                    caption="Point",
                ),
            ],
            filename="test.docx",
        )
        table_types = {0: "record"}
        converter = DocumentConverter()
        result = converter.convert(raw, table_types, raw.tables)
        assert len(result["records"]) == 1
        assert result["records"][0].name == "Point"
        assert len(result["records"][0].fields) == 1
        assert result["records"][0].fields[0].name == "X"


# ---------------------------------------------------------------------------
# Task 9.9 — Type_patterns matching
# ---------------------------------------------------------------------------


class TestConverterTypePatterns:
    def test_match_enum_by_heading(self):
        """Heading exactly 'enums' or 'enum' is classified as enum (anchored)."""
        converter = DocumentConverter()
        assert converter._match_type_pattern("Enums") == "enum"
        assert converter._match_type_pattern("Enum") == "enum"
        assert converter._match_type_pattern("enums") == "enum"
        # Anchored patterns (^...$) require exact match
        assert converter._match_type_pattern("Enums and Flags") is None
        assert converter._match_type_pattern("enum Values") is None

    def test_match_error_code_by_heading(self):
        """Heading exactly matching error pattern is classified."""
        converter = DocumentConverter()
        assert converter._match_type_pattern("Errors") == "error_code"
        assert converter._match_type_pattern("Error-Codes") == "error_code"
        assert converter._match_type_pattern("error_codes") == "error_code"
        assert converter._match_type_pattern("Error Codes") is None

    def test_match_record_by_heading(self):
        """Heading exactly matching record/model is classified as record."""
        converter = DocumentConverter()
        assert converter._match_type_pattern("Records") == "record"
        assert converter._match_type_pattern("Record") == "record"
        assert converter._match_type_pattern("Models") == "record"
        assert converter._match_type_pattern("Model") == "record"
        assert converter._match_type_pattern("Model Definitions") is None

    def test_no_match_returns_none(self):
        """Heading that doesn't match any pattern returns None."""
        converter = DocumentConverter()
        assert converter._match_type_pattern("Methods") is None
        assert converter._match_type_pattern("Properties") is None
        assert converter._match_type_pattern("Some Other Topic") is None

    def test_custom_pattern_overrides_default(self):
        """Custom type_patterns override the defaults."""
        converter = DocumentConverter()
        converter._apply_config({
            "type_patterns": {
                "record": r"^(mydata)$",
            }
        })
        assert converter._match_type_pattern("MyData") == "record"
        assert converter._match_type_pattern("Records") is None

    def test_heading_text_makes_effective_type(self):
        """convert() uses heading pattern over detector type when matched."""
        raw = RawDocument(
            paragraphs=[
                RawParagraph(text="Errors", heading_level=2, position=0),
            ],
            tables=[
                RawTable(
                    headers=["", "", ""],
                    rows=[["", "E_INVALIDARG = 0x80070057", "Invalid arg"]],
                    position=1,
                ),
            ],
            filename="test.docx",
        )
        # The detector says "method", but the heading says "Errors"
        # → type_patterns match should reclassify as error_code
        table_types = {0: "method"}  # intentionally wrong
        converter = DocumentConverter()
        result = converter.convert(raw, table_types, raw.tables)

        # Should have error codes, not interfaces
        assert len(result["error_codes"]) == 1
        assert result["error_codes"][0].name == "E_INVALIDARG"
        assert result["interfaces"] == []


# ---------------------------------------------------------------------------
# Task 9.10 — Parent_interface assignment
# ---------------------------------------------------------------------------


class TestConverterParentInterface:
    def test_enum_gets_parent_interface_from_heading(self):
        """Enum under an interface heading gets parent_interface set."""
        raw = RawDocument(
            paragraphs=[
                RawParagraph(text="IFileDialog Interface", heading_level=2, position=0),
                RawParagraph(text="Enums", heading_level=3, position=1),
            ],
            tables=[
                RawTable(
                    headers=["", "", ""],
                    rows=[["", "None = 0", "No value"]],
                    position=2,
                ),
            ],
            filename="test.docx",
        )
        table_types = {0: "enum"}
        converter = DocumentConverter()
        result = converter.convert(raw, table_types, raw.tables)

        assert len(result["enums"]) == 1
        assert result["enums"][0].parent_interface == "IFileDialog"

    def test_error_code_gets_parent_interface(self):
        """Error codes under an interface heading get parent_interface set."""
        raw = RawDocument(
            paragraphs=[
                RawParagraph(text="IWindow Interface", heading_level=2, position=0),
                RawParagraph(text="Error Codes", heading_level=3, position=1),
            ],
            tables=[
                RawTable(
                    headers=["", "", ""],
                    rows=[["", "E_FAIL = 0x80004005", "General failure"]],
                    position=2,
                ),
            ],
            filename="test.docx",
        )
        table_types = {0: "error_code"}
        converter = DocumentConverter()
        result = converter.convert(raw, table_types, raw.tables)

        assert len(result["error_codes"]) == 1
        assert result["error_codes"][0].parent_interface == "IWindow"

    def test_record_gets_parent_interface(self):
        """Records under an interface heading get parent_interface set."""
        raw = RawDocument(
            paragraphs=[
                RawParagraph(text="INode Interface", heading_level=2, position=0),
                RawParagraph(text="Records", heading_level=3, position=1),
            ],
            tables=[
                RawTable(
                    headers=["Type", "Name"],
                    rows=[["int", "Id"]],
                    position=2,
                    caption="NodeInfo",
                ),
            ],
            filename="test.docx",
        )
        table_types = {0: "record"}
        converter = DocumentConverter()
        result = converter.convert(raw, table_types, raw.tables)

        assert len(result["records"]) == 1
        assert result["records"][0].parent_interface == "INode"

    def test_no_interface_heading_yields_none_parent(self):
        """Entity without an interface heading has parent_interface None."""
        raw = RawDocument(
            paragraphs=[],  # no paragraphs → no heading context
            tables=[
                RawTable(
                    headers=["", "", ""],
                    rows=[["", "None = 0", "No value"]],
                    position=0,
                ),
            ],
            filename="test.docx",
        )
        table_types = {0: "enum"}
        converter = DocumentConverter()
        result = converter.convert(raw, table_types, raw.tables)

        assert len(result["enums"]) == 1
        assert result["enums"][0].parent_interface is None

    def test_deeply_nested_entity_finds_parent(self):
        """Entity nested multiple levels under an interface still finds it."""
        raw = RawDocument(
            paragraphs=[
                RawParagraph(text="IDataStore Interface", heading_level=1, position=0),
                RawParagraph(text="Connection", heading_level=2, position=1),
                RawParagraph(text="Error Codes", heading_level=3, position=2),
            ],
            tables=[
                RawTable(
                    headers=["", "", ""],
                    rows=[["", "E_CONNECT = 0x01", "Connection lost"]],
                    position=3,
                ),
            ],
            filename="test.docx",
        )
        table_types = {0: "error_code"}
        converter = DocumentConverter()
        result = converter.convert(raw, table_types, raw.tables)

        assert len(result["error_codes"]) == 1
        assert result["error_codes"][0].parent_interface == "IDataStore"
