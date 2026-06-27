"""Unit tests for ChunkGraphBuilder and ChunkTextFormatter configurable features.

Task 9.11 — Builder max_depth (nesting control)
Task 9.12 — Builder record support (APIRecord → ChunkNode)
Task 9.13 — Formatter config application (format_style, include_signatures, include_descriptions)
Task 9.14 — Formatter record formatting
"""

from src.domain.rag.api_docs.chunking.builder import ChunkGraphBuilder
from src.domain.rag.api_docs.chunking.text_formatter import ChunkTextFormatter
from src.domain.rag.api_docs.model.models import (
    APIEnum,
    APIEnumValue,
    APIErrorCode,
    APIFunction,
    APIInterface,
    APIParameter,
    APIProperty,
    APIRecord,
    APIRecordField,
)

# ── Shared fixtures ────────────────────────────────────────────────────


def _make_interface() -> APIInterface:
    """Interface with one method (2 params) and one property."""
    return APIInterface(
        name="INode",
        description="Node interface",
        methods=[
            APIFunction(
                name="Create",
                return_type="void",
                description="Creates a node",
                parameters=[
                    APIParameter(name="x", type_annotation="double"),
                    APIParameter(name="y", type_annotation="double"),
                ],
            ),
        ],
        properties=[
            APIProperty(name="Count", type_annotation="int", access="read"),
        ],
    )


def _make_record() -> APIRecord:
    """A simple record with two fields."""
    return APIRecord(
        name="Point",
        description="A 2D point",
        fields=[
            APIRecordField(name="X", type_annotation="int", description="X coordinate"),
            APIRecordField(name="Y", type_annotation="int", description="Y coordinate"),
        ],
    )


def _make_enum() -> APIEnum:
    """An enum with two values."""
    return APIEnum(
        name="Color",
        values=[
            APIEnumValue(name="Red", value=0),
            APIEnumValue(name="Blue", value=1),
        ],
    )


# ══════════════════════════════════════════════════════════════════════════
# Task 9.11 — Builder max_depth
# ══════════════════════════════════════════════════════════════════════════


class TestBuilderMaxDepth:
    def test_default_max_depth(self):
        """Builder has sensible default max_depth (5)."""
        builder = ChunkGraphBuilder()
        assert builder.max_depth == 5

    def test_max_depth_1_no_children(self):
        """max_depth=1: only interface nodes, no methods/properties."""
        builder = ChunkGraphBuilder()
        iface = _make_interface()
        graph = builder.build(
            interfaces=[iface], source_doc="test",
            config={"max_depth": 1},
        )
        kinds = {n.kind for n in graph.nodes.values()}
        assert kinds == {"interface"}
        assert len(graph.nodes) == 1

    def test_max_depth_2_stops_at_methods(self):
        """max_depth=2: interfaces and methods/properties, but no params."""
        builder = ChunkGraphBuilder()
        iface = _make_interface()
        graph = builder.build(
            interfaces=[iface], source_doc="test",
            config={"max_depth": 2},
        )
        kinds = {n.kind for n in graph.nodes.values()}
        assert "interface" in kinds
        assert "method" in kinds
        assert "property" in kinds
        assert "parameter" not in kinds

    def test_max_depth_1_stops_enum_values(self):
        """max_depth=1: enum node created but values are not."""
        builder = ChunkGraphBuilder()
        enum = _make_enum()
        graph = builder.build(
            enums=[enum], source_doc="test",
            config={"max_depth": 1},
        )
        kinds = {n.kind for n in graph.nodes.values()}
        assert "enum" in kinds
        assert "enum_value" not in kinds

    def test_max_depth_3_includes_params(self):
        """max_depth=3: full hierarchy including parameters."""
        builder = ChunkGraphBuilder()
        iface = _make_interface()
        graph = builder.build(
            interfaces=[iface], source_doc="test",
            config={"max_depth": 3},
        )
        kinds = {n.kind for n in graph.nodes.values()}
        assert "parameter" in kinds

    def test_config_none_resets_to_default(self):
        """config=None resets builder to defaults (max_depth=5)."""
        builder = ChunkGraphBuilder()
        iface = _make_interface()
        builder.build(
            interfaces=[iface], source_doc="test",
            config={"max_depth": 1},
        )
        assert builder.max_depth == 1

        # Build again without config — should reset to default
        builder2 = ChunkGraphBuilder()
        graph2 = builder2.build(
            interfaces=[iface], source_doc="test",
            config=None,
        )
        assert builder2.max_depth == 5
        kinds = {n.kind for n in graph2.nodes.values()}
        assert "parameter" in kinds  # params included with default depth

    def test_backward_compatibility_no_config(self):
        """build() without config argument works (positional compat)."""
        builder = ChunkGraphBuilder()
        iface = _make_interface()
        graph = builder.build([iface], source_doc="test")
        assert len(graph.nodes) > 1


# ══════════════════════════════════════════════════════════════════════════
# Task 9.12 — Builder record support
# ══════════════════════════════════════════════════════════════════════════


class TestBuilderRecords:
    def test_build_with_record(self):
        """Builder creates record node with fields."""
        builder = ChunkGraphBuilder()
        record = _make_record()
        graph = builder.build(records=[record], source_doc="test")

        record_nodes = [n for n in graph.nodes.values() if n.kind == "record"]
        field_nodes = [n for n in graph.nodes.values() if n.kind == "record_field"]

        assert len(record_nodes) == 1
        assert len(field_nodes) == 2

        record_meta = record_nodes[0].metadata
        assert record_meta["kind"] == "record"
        assert record_meta["record_name"] == "Point"
        assert record_meta["type_name"] == "Point"

    def test_record_is_root_node(self):
        """Record node is a root node (level 0, parent_id None)."""
        builder = ChunkGraphBuilder()
        record = _make_record()
        graph = builder.build(records=[record], source_doc="test")

        assert len(graph.root_node_ids) == 1
        root_id = graph.root_node_ids[0]
        root_node = graph.nodes[root_id]
        assert root_node.kind == "record"
        assert root_node.level == 0
        assert root_node.parent_id is None

    def test_record_fields_metadata(self):
        """Record field nodes have correct metadata."""
        builder = ChunkGraphBuilder()
        record = _make_record()
        graph = builder.build(records=[record], source_doc="test")

        field_nodes = sorted(
            [n for n in graph.nodes.values() if n.kind == "record_field"],
            key=lambda n: n.metadata.get("name", ""),
        )
        assert field_nodes[0].metadata["name"] == "X"
        assert field_nodes[0].metadata["type_annotation"] == "int"
        assert field_nodes[0].metadata["description"] == "X coordinate"
        assert field_nodes[0].metadata["record_name"] == "Point"

        assert field_nodes[1].metadata["name"] == "Y"

    def test_record_field_parent_child_links(self):
        """Record field nodes are children of the record node."""
        builder = ChunkGraphBuilder()
        record = _make_record()
        graph = builder.build(records=[record], source_doc="test")

        record_node = next(n for n in graph.nodes.values() if n.kind == "record")
        field_nodes = [n for n in graph.nodes.values() if n.kind == "record_field"]

        for fn in field_nodes:
            assert fn.parent_id == record_node.chunk_id
        for fn in field_nodes:
            assert fn.chunk_id in record_node.child_ids

    def test_record_levels(self):
        """Record is level 0, fields are level 1."""
        builder = ChunkGraphBuilder()
        record = _make_record()
        graph = builder.build(records=[record], source_doc="test")

        record_node = next(n for n in graph.nodes.values() if n.kind == "record")
        assert record_node.level == 0

        for fn in graph.nodes.values():
            if fn.kind == "record_field":
                assert fn.level == 1

    def test_record_fields_respect_max_depth(self):
        """max_depth=1 suppresses record fields."""
        builder = ChunkGraphBuilder()
        record = _make_record()
        graph = builder.build(
            records=[record], source_doc="test",
            config={"max_depth": 1},
        )
        kinds = {n.kind for n in graph.nodes.values()}
        assert "record" in kinds
        assert "record_field" not in kinds

    def test_record_with_parent_interface_metadata(self):
        """Record metadata includes interface_name from parent_interface."""
        builder = ChunkGraphBuilder()
        record = APIRecord(
            name="NodeData",
            fields=[APIRecordField(name="Id", type_annotation="int")],
            parent_interface="INode",
        )
        graph = builder.build(records=[record], source_doc="test")

        record_node = next(n for n in graph.nodes.values() if n.kind == "record")
        assert record_node.metadata["interface_name"] == "INode"

    def test_build_with_empty_records(self):
        """Empty records list produces no record nodes."""
        builder = ChunkGraphBuilder()
        graph = builder.build(records=[], source_doc="test")
        assert len(graph.nodes) == 0

    def test_build_with_mixed_types(self):
        """Builder handles interfaces, enums, error_codes, and records together."""
        builder = ChunkGraphBuilder()
        iface = _make_interface()
        enum = _make_enum()
        ec = APIErrorCode(name="E_FAIL", code=0x01)
        record = _make_record()

        graph = builder.build(
            interfaces=[iface],
            enums=[enum],
            error_codes=[ec],
            records=[record],
            source_doc="test",
        )

        kinds = {n.kind for n in graph.nodes.values()}
        assert "interface" in kinds
        assert "method" in kinds
        assert "enum" in kinds
        assert "error_code" in kinds
        assert "record" in kinds
        assert "record_field" in kinds
        # All are root nodes
        root_kinds = {graph.nodes[nid].kind for nid in graph.root_node_ids}
        assert "interface" in root_kinds
        assert "enum" in root_kinds
        assert "error_code" in root_kinds
        assert "record" in root_kinds


# ══════════════════════════════════════════════════════════════════════════
# Task 9.13 — Formatter config application
# ══════════════════════════════════════════════════════════════════════════


class TestFormatterConfig:
    def test_default_format_style(self):
        """Formatter defaults to 'detailed'."""
        formatter = ChunkTextFormatter()
        assert formatter.format_style == "detailed"
        assert formatter.include_signatures is True
        assert formatter.include_descriptions is True

    def test_compact_format_style(self):
        """Compact format produces different output than detailed."""
        formatter = ChunkTextFormatter()
        iface = _make_interface()
        builder = ChunkGraphBuilder()
        graph = builder.build(interfaces=[iface], source_doc="test")

        # Detailed
        formatter.format_graph(graph, interfaces=[iface], config={"format_style": "detailed"})
        iface_node_detailed = next(
            n for n in graph.nodes.values() if n.kind == "interface"
        )

        # Compact
        graph2 = builder.build(interfaces=[iface], source_doc="test")
        formatter.format_graph(graph2, interfaces=[iface], config={"format_style": "compact"})
        iface_node_compact = next(
            n for n in graph2.nodes.values() if n.kind == "interface"
        )

        assert "Interface " in iface_node_detailed.content
        assert "I: " in iface_node_compact.content
        assert iface_node_detailed.content != iface_node_compact.content

    def test_include_signatures_false(self):
        """Setting include_signatures=False omits method signatures."""
        formatter = ChunkTextFormatter()
        iface = _make_interface()
        builder = ChunkGraphBuilder()
        graph = builder.build(interfaces=[iface], source_doc="test")

        formatter.format_graph(
            graph, interfaces=[iface],
            config={"include_signatures": False},
        )
        method_node = next(n for n in graph.nodes.values() if n.kind == "method")
        # Should not have the full signature pattern (-> void, x: double, etc.)
        assert "->" not in method_node.content
        # But the name should still be there
        assert "Create" in method_node.content

    def test_include_descriptions_false(self):
        """Setting include_descriptions=False omits descriptions."""
        formatter = ChunkTextFormatter()
        iface = _make_interface()
        builder = ChunkGraphBuilder()
        graph = builder.build(interfaces=[iface], source_doc="test")

        formatter.format_graph(
            graph, interfaces=[iface],
            config={"include_descriptions": False},
        )
        method_node = next(n for n in graph.nodes.values() if n.kind == "method")
        # Description "Creates a node" should NOT be present
        assert "Creates a node" not in method_node.content

    def test_include_descriptions_false_on_interface(self):
        """include_descriptions=False does not include description on interface."""
        formatter = ChunkTextFormatter()
        iface = _make_interface()
        builder = ChunkGraphBuilder()
        graph = builder.build(interfaces=[iface], source_doc="test")

        formatter.format_graph(
            graph, interfaces=[iface],
            config={"include_descriptions": False},
        )
        iface_node = next(n for n in graph.nodes.values() if n.kind == "interface")
        assert "Node interface" not in iface_node.content

    def test_includes_both_by_default(self):
        """Default config includes both signatures and descriptions."""
        formatter = ChunkTextFormatter()
        iface = _make_interface()
        builder = ChunkGraphBuilder()
        graph = builder.build(interfaces=[iface], source_doc="test")

        formatter.format_graph(graph, interfaces=[iface])
        method_node = next(n for n in graph.nodes.values() if n.kind == "method")
        assert "->" in method_node.content
        assert "Creates a node" in method_node.content

    def test_config_none_resets_to_defaults(self):
        """passing config=None resets formatter to defaults."""
        formatter = ChunkTextFormatter()

        # Set non-default values
        iface = _make_interface()
        builder = ChunkGraphBuilder()
        graph = builder.build(interfaces=[iface], source_doc="test")
        formatter.format_graph(
            graph, interfaces=[iface],
            config={"format_style": "compact", "include_signatures": False},
        )
        assert formatter.format_style == "compact"

        # Reset with None config
        graph2 = builder.build(interfaces=[iface], source_doc="test")
        formatter.format_graph(graph2, interfaces=[iface], config=None)
        assert formatter.format_style == "detailed"
        assert formatter.include_signatures is True


# ══════════════════════════════════════════════════════════════════════════
# Task 9.14 — Formatter record formatting
# ══════════════════════════════════════════════════════════════════════════


class TestFormatterRecords:
    def test_format_record_with_domain_object(self):
        """Record formatted with domain object produces expected output."""
        formatter = ChunkTextFormatter()
        record = _make_record()
        builder = ChunkGraphBuilder()
        graph = builder.build(records=[record], source_doc="test")

        formatter.format_graph(graph, records=[record])
        record_node = next(n for n in graph.nodes.values() if n.kind == "record")
        assert "Record Point" in record_node.content
        assert "Fields" in record_node.content
        assert "X" in record_node.content
        assert "Y" in record_node.content

    def test_format_record_compact(self):
        """Record formatted with compact style uses short prefix."""
        formatter = ChunkTextFormatter()
        record = _make_record()
        builder = ChunkGraphBuilder()
        graph = builder.build(records=[record], source_doc="test")

        formatter.format_graph(
            graph, records=[record],
            config={"format_style": "compact"},
        )
        record_node = next(n for n in graph.nodes.values() if n.kind == "record")
        assert "R: Point" in record_node.content
        assert "F: " in record_node.content or "F:" in record_node.content

    def test_format_record_field_with_domain_object(self):
        """Record field formatted with domain object."""
        formatter = ChunkTextFormatter()
        record = _make_record()
        builder = ChunkGraphBuilder()
        graph = builder.build(records=[record], source_doc="test")

        formatter.format_graph(graph, records=[record])
        field_nodes = sorted(
            [n for n in graph.nodes.values() if n.kind == "record_field"],
            key=lambda n: n.metadata.get("name", ""),
        )
        assert field_nodes[0].content == "X: int - X coordinate"
        assert field_nodes[1].content == "Y: int - Y coordinate"

    def test_format_record_field_without_description(self):
        """Record field without description shows base format."""
        formatter = ChunkTextFormatter()
        record = APIRecord(
            name="Simple",
            fields=[APIRecordField(name="Id", type_annotation="int")],
        )
        builder = ChunkGraphBuilder()
        graph = builder.build(records=[record], source_doc="test")

        formatter.format_graph(graph, records=[record])
        field_node = next(n for n in graph.nodes.values() if n.kind == "record_field")
        assert field_node.content == "Id: int"

    def test_format_record_field_description_suppressed(self):
        """include_descriptions=False suppresses field description."""
        formatter = ChunkTextFormatter()
        record = _make_record()
        builder = ChunkGraphBuilder()
        graph = builder.build(records=[record], source_doc="test")

        formatter.format_graph(
            graph, records=[record],
            config={"include_descriptions": False},
        )
        field_node = next(n for n in graph.nodes.values() if n.kind == "record_field")
        # Should not include description
        assert "X coordinate" not in field_node.content
        assert "X: int" in field_node.content

    def test_format_record_metadata_fallback(self):
        """Record formatting falls back to metadata when domain object missing."""
        formatter = ChunkTextFormatter()
        record = _make_record()
        builder = ChunkGraphBuilder()
        graph = builder.build(records=[record], source_doc="test")

        # Format without records list → metadata fallback
        formatter.format_graph(graph)
        record_node = next(n for n in graph.nodes.values() if n.kind == "record")
        assert "Record Point" in record_node.content

    def test_format_record_field_metadata_fallback(self):
        """Record field formatting falls back to metadata correctly."""
        formatter = ChunkTextFormatter()
        record = _make_record()
        builder = ChunkGraphBuilder()
        graph = builder.build(records=[record], source_doc="test")

        formatter.format_graph(graph)
        field_nodes = sorted(
            [n for n in graph.nodes.values() if n.kind == "record_field"],
            key=lambda n: n.metadata.get("name", ""),
        )
        # Fallback uses metadata → type defaults to "any" if not in metadata
        assert "X" in field_nodes[0].content
