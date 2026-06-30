"""Unit tests for chunk graph builder, serialization, and text formatting.

Task 9.3 — Tests hierarchy, parent-child relationships, serialization round-trip,
and text formatting for each node type.
"""

import logging

from src.domain.rag.api_docs.chunking.builder import ChunkGraphBuilder
from src.domain.rag.api_docs.chunking.serializer import (
    deserialize_chunk_graph,
    serialize_chunk_graph,
)
from src.domain.rag.api_docs.chunking.text_formatter import ChunkTextFormatter
from src.domain.rag.api_docs.extraction.converter import GenericTableEntry
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

BUILDER = ChunkGraphBuilder()
FORMATTER = ChunkTextFormatter()


# ---------------------------------------------------------------------------
# ChunkGraphBuilder — interface with one method and two parameters
# ---------------------------------------------------------------------------


def _make_single_interface() -> APIInterface:
    return APIInterface(
        name="INode",
        description="Node interface",
        methods=[
            APIFunction(
                name="Create",
                return_type="void",
                description="Creates a node",
                parameters=[
                    APIParameter(name="x", type_annotation="double", description="X coord"),
                    APIParameter(name="y", type_annotation="double", description="Y coord"),
                ],
            ),
        ],
        properties=[
            APIProperty(name="Count", type_annotation="int", access="read", description="Count"),
        ],
    )


def test_build_interface_hierarchy():
    """Builder creates correct hierarchy: interface -> method -> parameter."""
    iface = _make_single_interface()
    graph = BUILDER.build(interfaces=[iface], source_doc="test")

    assert len(graph.nodes) == 1 + 1 + 2 + 1  # interface + method + 2 params + property

    # Find nodes by kind
    iface_nodes = [n for n in graph.nodes.values() if n.kind == "interface"]
    method_nodes = [n for n in graph.nodes.values() if n.kind == "method"]
    param_nodes = [n for n in graph.nodes.values() if n.kind == "parameter"]
    prop_nodes = [n for n in graph.nodes.values() if n.kind == "property"]

    assert len(iface_nodes) == 1
    assert len(method_nodes) == 1
    assert len(param_nodes) == 2
    assert len(prop_nodes) == 1


def test_build_parent_child_relationships():
    """Parent_id and child_ids are correctly linked."""
    iface = _make_single_interface()
    graph = BUILDER.build(interfaces=[iface], source_doc="test")

    iface_node = next(n for n in graph.nodes.values() if n.kind == "interface")
    method_node = next(n for n in graph.nodes.values() if n.kind == "method")
    param_nodes = [n for n in graph.nodes.values() if n.kind == "parameter"]

    # Method's parent is the interface
    assert method_node.parent_id == iface_node.chunk_id
    # Interface has method as child
    assert method_node.chunk_id in iface_node.child_ids
    # Parameters have method as parent
    for pn in param_nodes:
        assert pn.parent_id == method_node.chunk_id
    # Method has parameters as children
    for pn in param_nodes:
        assert pn.chunk_id in method_node.child_ids


def test_build_root_node_ids():
    """Root nodes are tracked in graph.root_node_ids."""
    iface = _make_single_interface()
    graph = BUILDER.build(interfaces=[iface], source_doc="test")

    assert len(graph.root_node_ids) == 1
    root_node = graph.nodes[graph.root_node_ids[0]]
    assert root_node.kind == "interface"
    assert root_node.level == 0


def test_build_levels():
    """Levels are correct: interface=0, method=1, parameter=2."""
    iface = _make_single_interface()
    graph = BUILDER.build(interfaces=[iface], source_doc="test")
    for node in graph.nodes.values():
        if node.kind == "interface":
            assert node.level == 0
        elif node.kind == "method" or node.kind == "property":
            assert node.level == 1
        elif node.kind == "parameter":
            assert node.level == 2


def test_build_empty_lists():
    """Builder handles empty lists gracefully."""
    graph = BUILDER.build()
    assert len(graph.nodes) == 0
    assert len(graph.root_node_ids) == 0


def test_build_with_enums_and_error_codes():
    """Builder handles enums and error codes."""
    enum = APIEnum(
        name="NodeType",
        description="Types of nodes",
        values=[
            APIEnumValue(name="File", value=0),
            APIEnumValue(name="Directory", value=1),
        ],
    )
    ec = APIErrorCode(name="E_FAIL", code=0x80004005, description="General failure")

    graph = BUILDER.build(enums=[enum], error_codes=[ec], source_doc="test")

    enum_nodes = [n for n in graph.nodes.values() if n.kind == "enum"]
    ev_nodes = [n for n in graph.nodes.values() if n.kind == "enum_value"]
    ec_nodes = [n for n in graph.nodes.values() if n.kind == "error_code"]

    assert len(enum_nodes) == 1
    assert len(ev_nodes) == 2
    assert len(ec_nodes) == 1

    # Enum values have enum as parent
    enum_node = enum_nodes[0]
    for ev in ev_nodes:
        assert ev.parent_id == enum_node.chunk_id


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


def test_serialize_deserialize_roundtrip():
    """Serialization round-trip preserves all nodes and root IDs."""
    iface = _make_single_interface()
    graph = BUILDER.build(interfaces=[iface], source_doc="test")

    data = serialize_chunk_graph(graph)
    restored = deserialize_chunk_graph(data)

    assert len(restored.nodes) == len(graph.nodes)
    assert restored.root_node_ids == graph.root_node_ids

    # Compare each node
    for cid, original_node in graph.nodes.items():
        restored_node = restored.nodes[cid]
        assert restored_node.chunk_id == original_node.chunk_id
        assert restored_node.parent_id == original_node.parent_id
        assert restored_node.child_ids == original_node.child_ids
        assert restored_node.kind == original_node.kind
        assert restored_node.level == original_node.level
        assert restored_node.source_doc == original_node.source_doc


def test_serialize_deserialize_empty_graph():
    """Empty graph serialization round-trip."""
    graph = BUILDER.build()
    data = serialize_chunk_graph(graph)
    restored = deserialize_chunk_graph(data)
    assert len(restored.nodes) == 0
    assert restored.root_node_ids == []


# ---------------------------------------------------------------------------
# ChunkTextFormatter
# ---------------------------------------------------------------------------


def test_format_interface():
    """Interface content is formatted correctly."""
    iface = _make_single_interface()
    graph = BUILDER.build(interfaces=[iface], source_doc="test")
    FORMATTER.format_graph(graph, interfaces=[iface])

    iface_node = next(n for n in graph.nodes.values() if n.kind == "interface")
    assert "Interface INode" in iface_node.content
    assert "Create" in iface_node.content
    assert "Count" in iface_node.content


def test_format_method():
    """Method content includes signature and description."""
    iface = _make_single_interface()
    graph = BUILDER.build(interfaces=[iface], source_doc="test")
    FORMATTER.format_graph(graph, interfaces=[iface])

    method_node = next(n for n in graph.nodes.values() if n.kind == "method")
    assert "Create" in method_node.content
    assert "void" in method_node.content or "any" in method_node.content
    assert "Creates a node" in method_node.content


def test_format_parameter():
    """Parameter content includes name, type, and description."""
    iface = _make_single_interface()
    graph = BUILDER.build(interfaces=[iface], source_doc="test")
    FORMATTER.format_graph(graph, interfaces=[iface])

    param_nodes = [n for n in graph.nodes.values() if n.kind == "parameter"]
    for pn in param_nodes:
        assert pn.content
        assert pn.metadata.get("name") in pn.content


def test_format_property():
    """Property content includes name, type, access, and description."""
    iface = _make_single_interface()
    graph = BUILDER.build(interfaces=[iface], source_doc="test")
    FORMATTER.format_graph(graph, interfaces=[iface])

    prop_node = next(n for n in graph.nodes.values() if n.kind == "property")
    assert "Count" in prop_node.content
    assert "int" in prop_node.content
    assert "read" in prop_node.content


def test_format_enum_with_domain_objects():
    """Enum formatting uses domain objects for detailed content."""
    enum = APIEnum(
        name="NodeType",
        values=[
            APIEnumValue(name="File", value=0, description="A file node"),
            APIEnumValue(name="Directory", value=1),
        ],
    )
    graph = BUILDER.build(enums=[enum], source_doc="test")
    FORMATTER.format_graph(graph, enums=[enum])

    enum_node = next(n for n in graph.nodes.values() if n.kind == "enum")
    assert "Enum NodeType" in enum_node.content
    assert "File" in enum_node.content


def test_format_error_code():
    """Error code formatting includes code and description."""
    ec = APIErrorCode(name="E_FAIL", code=0x80004005, description="General failure")
    graph = BUILDER.build(error_codes=[ec], source_doc="test")
    FORMATTER.format_graph(graph, error_codes=[ec])

    ec_node = next(n for n in graph.nodes.values() if n.kind == "error_code")
    assert "E_FAIL" in ec_node.content
    assert "General failure" in ec_node.content


def test_format_metadata_fallback():
    """Formatter falls back to metadata when domain objects are not provided."""
    iface = _make_single_interface()
    graph = BUILDER.build(interfaces=[iface], source_doc="test")
    # Format without domain objects — uses metadata only
    FORMATTER.format_graph(graph)

    iface_node = next(n for n in graph.nodes.values() if n.kind == "interface")
    assert iface_node.content
    assert "Node" in iface_node.content


# ---------------------------------------------------------------------------
# Paragraph nodes (Task 2.3) — created from APIInterface.paragraphs
# ---------------------------------------------------------------------------


def test_build_paragraph_nodes():
    """Paragraphs from APIInterface.paragraphs create kind='paragraph' nodes
    at level 1."""
    iface = APIInterface(
        name="INode",
        description="Test",
        paragraphs=["First para text", "Second para text"],
    )
    graph = BUILDER.build(interfaces=[iface], source_doc="test")

    para_nodes = [n for n in graph.nodes.values() if n.kind == "paragraph"]
    assert len(para_nodes) == 2
    for node in para_nodes:
        assert node.kind == "paragraph"
        assert node.level == 1


def test_build_paragraph_parent_child():
    """Paragraph nodes have correct parent_id pointing to interface node,
    and are listed in the interface node's child_ids."""
    iface = APIInterface(
        name="INode",
        description="Test",
        paragraphs=["Some paragraph content"],
    )
    graph = BUILDER.build(interfaces=[iface], source_doc="test")

    iface_node = next(n for n in graph.nodes.values() if n.kind == "interface")
    para_node = next(n for n in graph.nodes.values() if n.kind == "paragraph")

    assert para_node.parent_id == iface_node.chunk_id
    assert para_node.chunk_id in iface_node.child_ids


def test_build_paragraph_metadata():
    """Paragraph node metadata contains interface_name and content keys."""
    iface = APIInterface(
        name="INode",
        description="Test",
        paragraphs=["Some paragraph content"],
    )
    graph = BUILDER.build(interfaces=[iface], source_doc="test")

    para_node = next(n for n in graph.nodes.values() if n.kind == "paragraph")
    assert para_node.metadata.get("interface_name") == "INode"
    assert para_node.metadata.get("content") == "Some paragraph content"


def test_build_paragraph_empty_list():
    """Empty paragraphs list creates no paragraph nodes."""
    iface = APIInterface(name="INode", description="Test", paragraphs=[])
    graph = BUILDER.build(interfaces=[iface], source_doc="test")

    para_nodes = [n for n in graph.nodes.values() if n.kind == "paragraph"]
    assert len(para_nodes) == 0


def test_build_paragraph_formatter():
    """ChunkTextFormatter formats paragraph by reading content from metadata."""
    iface = APIInterface(
        name="INode",
        description="Test",
        paragraphs=["Paragraph text for embedding"],
    )
    graph = BUILDER.build(interfaces=[iface], source_doc="test")
    FORMATTER.format_graph(graph)

    para_node = next(n for n in graph.nodes.values() if n.kind == "paragraph")
    assert para_node.content == "Paragraph text for embedding"


# ---------------------------------------------------------------------------
# Generic table chunk nodes (Task 3.2)
# ---------------------------------------------------------------------------


def test_build_generic_table_node():
    """_add_generic_table creates a kind='generic_table' node at level 1
    when parent_interface is set."""
    iface = APIInterface(name="INode", description="Test")
    entry = GenericTableEntry(
        heading_stack={},
        rows=[["a", "b"]],
        header_row=["X", "Y"],
        position=0,
        heading_text="Some heading",
        parent_interface="INode",
    )
    graph = BUILDER.build(
        interfaces=[iface], generic_tables=[entry], source_doc="test",
    )

    gt_nodes = [n for n in graph.nodes.values() if n.kind == "generic_table"]
    assert len(gt_nodes) == 1
    node = gt_nodes[0]
    assert node.kind == "generic_table"
    assert node.level == 1


def test_build_generic_table_parented():
    """The generic table node is parented under the correct interface node
    (matched by interface_name metadata)."""
    iface = APIInterface(name="INode", description="Test")
    entry = GenericTableEntry(
        heading_stack={},
        rows=[["a", "b"]],
        header_row=["X", "Y"],
        position=0,
        parent_interface="INode",
    )
    graph = BUILDER.build(
        interfaces=[iface], generic_tables=[entry], source_doc="test",
    )

    iface_node = next(n for n in graph.nodes.values() if n.kind == "interface")
    gt_node = next(n for n in graph.nodes.values() if n.kind == "generic_table")

    assert gt_node.parent_id == iface_node.chunk_id
    assert gt_node.chunk_id in iface_node.child_ids


def test_build_generic_table_metadata():
    """Metadata contains content (rendered table markdown), heading_text,
    and interface_name."""
    iface = APIInterface(name="INode", description="Test")
    entry = GenericTableEntry(
        heading_stack={2: "INode Interface"},
        rows=[["val1", "val2"]],
        header_row=["A", "B"],
        position=0,
        heading_text="INode Interface",
        parent_interface="INode",
    )
    graph = BUILDER.build(
        interfaces=[iface], generic_tables=[entry], source_doc="test",
    )

    gt_node = next(n for n in graph.nodes.values() if n.kind == "generic_table")
    meta = gt_node.metadata
    assert "content" in meta
    assert meta["heading_text"] == "INode Interface"
    assert meta["interface_name"] == "INode"
    # content should be rendered markdown
    assert "| A | B |" in meta["content"]


def test_build_generic_table_no_parent_interface(caplog):
    """If parent_interface is None, the generic table is skipped (logged)."""
    caplog.set_level(logging.DEBUG)
    entry = GenericTableEntry(
        heading_stack={},
        rows=[["a", "b"]],
        header_row=["X", "Y"],
        position=0,
        parent_interface=None,
    )
    graph = BUILDER.build(generic_tables=[entry], source_doc="test")

    gt_nodes = [n for n in graph.nodes.values() if n.kind == "generic_table"]
    assert len(gt_nodes) == 0
    assert any("no parent interface" in record.getMessage().lower()
               for record in caplog.records)


def test_build_generic_table_parent_not_found(caplog):
    """If the parent interface node is not found in the graph, the table
    is skipped (logged)."""
    caplog.set_level(logging.DEBUG)
    entry = GenericTableEntry(
        heading_stack={},
        rows=[["a"]],
        header_row=["X"],
        position=0,
        parent_interface="NonExistent",
    )
    graph = BUILDER.build(generic_tables=[entry], source_doc="test")

    gt_nodes = [n for n in graph.nodes.values() if n.kind == "generic_table"]
    assert len(gt_nodes) == 0
    assert any("not found in graph" in record.getMessage().lower()
               for record in caplog.records)


def test_build_generic_table_rendered_content():
    """The rendered content is a proper markdown-like pipe table
    (headers, separator, rows)."""
    iface = APIInterface(name="INode", description="Test")
    entry = GenericTableEntry(
        heading_stack={},
        rows=[["a", "b"], ["c", "d"]],
        header_row=["Col1", "Col2"],
        position=0,
        parent_interface="INode",
    )
    graph = BUILDER.build(
        interfaces=[iface], generic_tables=[entry], source_doc="test",
    )

    gt_node = next(n for n in graph.nodes.values() if n.kind == "generic_table")
    content = gt_node.metadata.get("content", "")

    assert "| Col1 | Col2 |" in content  # header
    assert "| --- | --- |" in content     # separator
    assert "| a | b |" in content         # data row 1
    assert "| c | d |" in content         # data row 2


def test_build_generic_table_pipe_escaping():
    """Cell content with pipes has pipes escaped as \\|."""
    iface = APIInterface(name="INode", description="Test")
    entry = GenericTableEntry(
        heading_stack={},
        rows=[["a|b", "c|d"]],
        header_row=["Col1", "Col2"],
        position=0,
        parent_interface="INode",
    )
    graph = BUILDER.build(
        interfaces=[iface], generic_tables=[entry], source_doc="test",
    )

    gt_node = next(n for n in graph.nodes.values() if n.kind == "generic_table")
    content = gt_node.metadata.get("content", "")

    # Escaped pipes in cell content
    assert r"a\|b" in content
    assert r"c\|d" in content
    # Markdown pipe separator should still be present
    assert content.startswith("|")


def test_build_generic_table_empty_rows():
    """_render_generic_table handles empty rows and header_row correctly."""
    # Empty header_row and empty rows
    entry1 = GenericTableEntry(
        heading_stack={}, rows=[], header_row=[], position=0,
    )
    result1 = ChunkGraphBuilder._render_generic_table(entry1)
    assert result1 == ""

    # Empty header_row but non-empty rows
    entry2 = GenericTableEntry(
        heading_stack={}, rows=[["a", "b"]], header_row=[], position=1,
    )
    result2 = ChunkGraphBuilder._render_generic_table(entry2)
    assert "| a | b |" in result2
    assert "|---" not in result2  # no separator without header

    # Non-empty header_row but empty rows
    entry3 = GenericTableEntry(
        heading_stack={}, rows=[], header_row=["Col1"], position=2,
    )
    result3 = ChunkGraphBuilder._render_generic_table(entry3)
    assert "| Col1 |" in result3
    assert "| --- |" in result3


def test_build_generic_table_formatter():
    """ChunkTextFormatter renders generic_table by reading content
    from metadata."""
    iface = APIInterface(name="INode", description="Test")
    entry = GenericTableEntry(
        heading_stack={},
        rows=[["x", "y"]],
        header_row=["H1", "H2"],
        position=0,
        parent_interface="INode",
    )
    graph = BUILDER.build(
        interfaces=[iface], generic_tables=[entry], source_doc="test",
    )
    FORMATTER.format_graph(graph)

    gt_node = next(n for n in graph.nodes.values() if n.kind == "generic_table")
    assert "| H1 | H2 |" in gt_node.content
    assert "| x | y |" in gt_node.content


# ---------------------------------------------------------------------------
# Enum value & record field metadata completeness (Task 6.4)
# ---------------------------------------------------------------------------


def test_build_enum_value_metadata_interface_name():
    """Enum value nodes have interface_name in metadata, sourced from
    enum_def.parent_interface."""
    enum = APIEnum(
        name="NodeType",
        values=[APIEnumValue(name="File", value=0)],
        parent_interface="INode",
    )
    graph = BUILDER.build(enums=[enum], source_doc="test")

    ev_node = next(n for n in graph.nodes.values() if n.kind == "enum_value")
    assert ev_node.metadata.get("interface_name") == "INode"


def test_build_enum_value_metadata_no_parent():
    """Enum value nodes WITHOUT a parent_interface have interface_name=''."""
    enum = APIEnum(
        name="NodeType",
        values=[APIEnumValue(name="File", value=0)],
        parent_interface=None,
    )
    graph = BUILDER.build(enums=[enum], source_doc="test")

    ev_node = next(n for n in graph.nodes.values() if n.kind == "enum_value")
    assert ev_node.metadata.get("interface_name") == ""


def test_build_record_field_metadata_interface_name():
    """Record field nodes have interface_name in metadata, sourced from
    record.parent_interface."""
    record = APIRecord(
        name="MyRecord",
        fields=[APIRecordField(name="Id", type_annotation="int")],
        parent_interface="INode",
    )
    graph = BUILDER.build(records=[record], source_doc="test")

    rf_node = next(n for n in graph.nodes.values() if n.kind == "record_field")
    assert rf_node.metadata.get("interface_name") == "INode"


def test_build_record_field_metadata_no_parent():
    """Record field nodes WITHOUT a parent_interface have interface_name=''."""
    record = APIRecord(
        name="MyRecord",
        fields=[APIRecordField(name="Id", type_annotation="int")],
        parent_interface=None,
    )
    graph = BUILDER.build(records=[record], source_doc="test")

    rf_node = next(n for n in graph.nodes.values() if n.kind == "record_field")
    assert rf_node.metadata.get("interface_name") == ""


def test_build_enum_value_all_metadata_keys():
    """Enum value nodes have all expected metadata keys:
    chunk_id, parent_id, kind, level, source_doc, type_name, name,
    value, description, interface_name."""
    enum = APIEnum(
        name="NodeType",
        values=[APIEnumValue(name="File", value=0, description="A file node")],
        parent_interface="INode",
    )
    graph = BUILDER.build(enums=[enum], source_doc="test")

    ev_node = next(n for n in graph.nodes.values() if n.kind == "enum_value")
    meta = ev_node.metadata
    assert "chunk_id" in meta
    assert "parent_id" in meta
    assert meta["kind"] == "enum_value"
    assert meta["level"] == 1
    assert "source_doc" in meta
    assert meta["type_name"] == "NodeType"
    assert meta["name"] == "File"
    assert meta["value"] == "0"
    assert meta["description"] == "A file node"
    assert meta["interface_name"] == "INode"


def test_build_record_field_all_metadata_keys():
    """Record field nodes have all expected metadata keys:
    chunk_id, parent_id, kind, level, source_doc, record_name, name,
    type_annotation, description, interface_name."""
    record = APIRecord(
        name="MyRecord",
        fields=[APIRecordField(name="Id", type_annotation="int",
                               description="Unique ID")],
        parent_interface="INode",
    )
    graph = BUILDER.build(records=[record], source_doc="test")

    rf_node = next(n for n in graph.nodes.values() if n.kind == "record_field")
    meta = rf_node.metadata
    assert "chunk_id" in meta
    assert "parent_id" in meta
    assert meta["kind"] == "record_field"
    assert meta["level"] == 1
    assert "source_doc" in meta
    assert meta["record_name"] == "MyRecord"
    assert meta["name"] == "Id"
    assert meta["type_annotation"] == "int"
    assert meta["description"] == "Unique ID"
    assert meta["interface_name"] == "INode"
