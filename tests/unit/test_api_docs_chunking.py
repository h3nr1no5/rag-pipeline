"""Unit tests for chunk graph builder, serialization, and text formatting.

Task 9.3 — Tests hierarchy, parent-child relationships, serialization round-trip,
and text formatting for each node type.
"""

from src.domain.rag.api_docs.chunking.builder import ChunkGraphBuilder
from src.domain.rag.api_docs.chunking.serializer import (
    deserialize_chunk_graph,
    serialize_chunk_graph,
)
from src.domain.rag.api_docs.chunking.text_formatter import ChunkTextFormatter
from src.domain.rag.api_docs.model.models import (
    APIEnum,
    APIEnumValue,
    APIErrorCode,
    APIFunction,
    APIInterface,
    APIParameter,
    APIProperty,
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
