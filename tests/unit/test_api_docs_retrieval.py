"""Unit tests for hybrid retriever: BM25 index, RRF fusion, link traversal, parent expansion.

Task 9.4 — Tests use a small chunk graph created directly in fixtures.
"""

import pytest

from src.domain.rag.api_docs.chunking.builder import ChunkGraph, ChunkGraphBuilder
from src.domain.rag.api_docs.model.models import (
    APIEnum,
    APIEnumValue,
    APIFunction,
    APIInterface,
    APIParameter,
    APIProperty,
)
from src.domain.rag.api_docs.retrieval.bm25_index import ApiBm25Index
from src.domain.rag.api_docs.retrieval.link_traverser import LinkTraverser
from src.domain.rag.api_docs.retrieval.parent_expander import ParentExpander
from src.domain.rag.api_docs.retrieval.rrf import RrfFusion

# ---------------------------------------------------------------------------
# Fixture: small chunk graph
# ---------------------------------------------------------------------------


def _make_sample_graph() -> ChunkGraph:
    """Create a small chunk graph with two interfaces, a method, a property,
    and a parameter for BM25 / link / parent tests."""
    builder = ChunkGraphBuilder()
    iface1 = APIInterface(
        name="INode",
        description="Node interface",
        methods=[
            APIFunction(
                name="Create",
                return_type="INode",
                parameters=[
                    APIParameter(name="parent", type_annotation="INode"),
                ],
            ),
        ],
        properties=[APIProperty(name="Name", type_annotation="string")],
    )
    iface2 = APIInterface(
        name="IElement",
        description="Element interface",
        methods=[
            APIFunction(name="Render", return_type="void"),
        ],
    )
    return builder.build(
        interfaces=[iface1, iface2],
        source_doc="test-doc",
    )


def _make_link_test_graph() -> ChunkGraph:
    """Create a graph with content that has cross-references for link traversal."""
    builder = ChunkGraphBuilder()
    iface1 = APIInterface(
        name="INode",
        description="Node interface referencing IElement",
        methods=[
            APIFunction(
                name="Create",
                return_type="INode",
                parameters=[APIParameter(name="elem", type_annotation="IElement")],
            ),
        ],
        properties=[],
    )
    iface2 = APIInterface(
        name="IElement",
        description="Element interface",
        methods=[APIFunction(name="Render", return_type="void")],
    )
    graph = builder.build(interfaces=[iface1, iface2], source_doc="test")
    # Populate content so link traverser can find references
    for node in graph.nodes.values():
        meta = node.metadata
        if node.kind == "interface":
            node.content = f"Interface {meta.get('interface_name', '')}"
        elif node.kind == "method":
            node.content = f"{meta.get('function_name', '')} -> {meta.get('return_type', 'void')}"
        elif node.kind == "parameter":
            node.content = f"{meta.get('name', '')}: {meta.get('type_annotation', 'any')}"
        elif node.kind == "property":
            node.content = f"{meta.get('name', '')}: {meta.get('type_annotation', 'any')}"
    return graph


# ---------------------------------------------------------------------------
# ApiBm25Index
# ---------------------------------------------------------------------------


def test_bm25_index_add_graph():
    """BM25 index is populated after add_graph."""
    graph = _make_sample_graph()
    index = ApiBm25Index()
    index.add_graph(graph)
    assert len(index.chunk_ids) == len(graph.nodes)
    assert index._bm25 is not None


def test_bm25_index_search_by_function_name():
    """Searching by a function name returns ranked results."""
    graph = _make_sample_graph()
    index = ApiBm25Index()
    index.add_graph(graph)
    results = index.search("Create")
    assert len(results) > 0
    # The top result should be the "Create" method or its containing interface
    top_id = results[0][0]
    top_node = graph.nodes[top_id]
    assert top_node.metadata.get("function_name") == "Create" or \
           top_node.metadata.get("interface_name") == "INode"


def test_bm25_index_search_returns_scores():
    """BM25 search returns scores that are normalized to [0, 1]."""
    graph = _make_sample_graph()
    index = ApiBm25Index()
    index.add_graph(graph)
    results = index.search("Create", top_k=5)
    assert all(0.0 <= score <= 1.0 for _, score in results)


def test_bm25_index_empty():
    """Search on empty index returns empty list."""
    index = ApiBm25Index()
    results = index.search("anything")
    assert results == []


def test_bm25_index_empty_graph():
    """add_graph with empty graph logs warning and stays empty."""
    graph = ChunkGraph()
    index = ApiBm25Index()
    index.add_graph(graph)
    assert index.chunk_ids == []
    assert index._bm25 is None


def test_bm25_index_blank_query():
    """Blank query returns empty list."""
    graph = _make_sample_graph()
    index = ApiBm25Index()
    index.add_graph(graph)
    assert index.search("") == []
    assert index.search("   ") == []


# ---------------------------------------------------------------------------
# _tokenize  (camelCase-aware tokenization)
# ---------------------------------------------------------------------------


class TestTokenize:
    """Unit tests for ApiBm25Index._tokenize()."""

    def test_tokenize_camelcase_start_selection(self) -> None:
        """StartSelection → ['start', 'selection']"""
        assert ApiBm25Index._tokenize("StartSelection") == ["start", "selection"]

    def test_tokenize_camelcase_pdf_parser(self) -> None:
        """PDFParser → ['pdf', 'parser']"""
        assert ApiBm25Index._tokenize("PDFParser") == ["pdf", "parser"]

    def test_tokenize_single_word(self) -> None:
        """initialize → ['initialize']"""
        assert ApiBm25Index._tokenize("initialize") == ["initialize"]

    def test_tokenize_camelcase_parse_xml(self) -> None:
        """parseXML → ['parse', 'xml']"""
        assert ApiBm25Index._tokenize("parseXML") == ["parse", "xml"]

    def test_tokenize_regular_text(self) -> None:
        """'simple text' → ['simple', 'text']  (regular text unchanged)"""
        assert ApiBm25Index._tokenize("simple text") == ["simple", "text"]

    def test_tokenize_empty_string(self) -> None:
        """'' → [] (empty string)"""
        assert ApiBm25Index._tokenize("") == []


# ---------------------------------------------------------------------------
# RrfFusion
# ---------------------------------------------------------------------------


def test_rrf_fusion_two_lists():
    """RRF correctly fuses two ranked lists into one."""
    fusion = RrfFusion(k=60)
    list_a = [("doc1", 0.9), ("doc2", 0.8)]
    list_b = [("doc2", 0.95), ("doc3", 0.85)]

    fused = fusion.fuse([list_a, list_b])
    assert len(fused) == 3
    # doc2 appears in both lists so should have highest RRF score
    assert fused[0][0] == "doc2"


def test_rrf_fusion_scores():
    """RRF produces scores based on reciprocal rank."""
    fusion = RrfFusion(k=1)  # Use k=1 for more contrast
    list_a = [("doc1", 1.0)]
    list_b = [("doc1", 1.0)]

    fused = fusion.fuse([list_a, list_b])
    # doc1 is rank 1 in both lists → RRF = 1/(1+1) + 1/(1+1) = 1.0
    doc_id, score = fused[0]
    assert doc_id == "doc1"
    assert score == pytest.approx(1.0)


def test_rrf_fusion_empty_input():
    """Fusing empty lists returns empty list."""
    fusion = RrfFusion()
    assert fusion.fuse([]) == []
    assert fusion.fuse([[], []]) == []


def test_rrf_fusion_deduplicates():
    """Same doc in multiple lists appears once in output."""
    fusion = RrfFusion(k=60)
    lists = [
        [("doc1", 1.0), ("doc2", 0.5)],
        [("doc1", 0.9)],
    ]
    fused = fusion.fuse(lists)
    doc_ids = [doc_id for doc_id, _ in fused]
    assert doc_ids.count("doc1") == 1  # no duplicates


# ---------------------------------------------------------------------------
# LinkTraverser
# ---------------------------------------------------------------------------


def test_link_traverser_finds_parent_interface():
    """Traversing from a method finds its parent interface."""
    graph = _make_link_test_graph()
    method_node = next(n for n in graph.nodes.values() if n.kind == "method")
    traverser = LinkTraverser()
    result = traverser.traverse([method_node.chunk_id], graph, max_depth=2)
    # Should contain method + parent interface
    assert method_node.chunk_id in result
    assert method_node.parent_id in result


def test_link_traverser_max_depth():
    """max_depth prevents infinite loops."""
    graph = _make_link_test_graph()
    all_ids = list(graph.nodes.keys())
    traverser = LinkTraverser()
    # With depth 0, only the starting nodes are returned
    result = traverser.traverse(all_ids, graph, max_depth=0)
    assert len(result) <= len(all_ids)


def test_link_traverser_empty_input():
    """Empty input returns empty list."""
    graph = _make_link_test_graph()
    traverser = LinkTraverser()
    assert traverser.traverse([], graph) == []


def test_link_traverser_no_references():
    """Nodes without references are returned as-is."""
    graph = _make_link_test_graph()
    # Property nodes typically don't have references in their content
    prop_nodes = [n for n in graph.nodes.values() if n.kind == "property"]
    if prop_nodes:
        traverser = LinkTraverser()
        result = traverser.traverse([prop_nodes[0].chunk_id], graph)
        assert prop_nodes[0].chunk_id in result


# ---------------------------------------------------------------------------
# LinkTraverser — enum cross-references (Task 5.4)
# ---------------------------------------------------------------------------


def _make_enum_link_test_graph() -> ChunkGraph:
    """Create a test graph with enum nodes for link-traversal tests.

    Contains:
    - Interface INode referencing EMaterialType in its content
    - Enum EMaterialType with values
    - Interface IElement (backward-compat test)
    """
    builder = ChunkGraphBuilder()
    iface_inode = APIInterface(
        name="INode",
        description="Node interface referencing EMaterialType",
        methods=[
            APIFunction(
                name="Create",
                return_type="INode",
                parameters=[
                    APIParameter(name="material", type_annotation="EMaterialType"),
                ],
            ),
        ],
    )
    iface_ielement = APIInterface(
        name="IElement",
        description="Element interface",
        methods=[APIFunction(name="Render", return_type="void")],
    )
    enum_material = APIEnum(
        name="EMaterialType",
        description="Material types",
        values=[
            APIEnumValue(name="Wood", value=0),
            APIEnumValue(name="Steel", value=1),
        ],
    )
    graph = builder.build(
        interfaces=[iface_inode, iface_ielement],
        enums=[enum_material],
        source_doc="test",
    )
    # Populate content so link traverser can find references
    for node in graph.nodes.values():
        meta = node.metadata
        if node.kind == "interface":
            name = meta.get("interface_name", "")
            if name == "INode":
                node.content = "Interface INode with EMaterialType support"
            elif name == "IElement":
                node.content = "Interface IElement"
        elif node.kind == "method":
            func_name = meta.get("function_name", "")
            if func_name == "Create":
                node.content = "Create(material: EMaterialType) -> INode"
            else:
                node.content = f"{func_name}()"
        elif node.kind == "enum":
            node.content = f"Enum {meta.get('type_name', '')}"
        elif node.kind == "enum_value":
            node.content = f"{meta.get('name', '')} = {meta.get('value', '')}"
        elif node.kind == "parameter":
            node.content = f"{meta.get('name', '')}: {meta.get('type_annotation', 'any')}"
    return graph


def test_link_traverser_e_prefix_enum():
    """E-prefix names (e.g. EMaterialType) in content are followed
    by LinkTraverser."""
    graph = _make_enum_link_test_graph()
    traverser = LinkTraverser()

    # Start from the INode interface
    iface_node = next(
        n for n in graph.nodes.values()
        if n.kind == "interface" and n.metadata.get("interface_name") == "INode"
    )
    result = traverser.traverse([iface_node.chunk_id], graph, max_depth=2)

    enum_node = next(n for n in graph.nodes.values() if n.kind == "enum")
    assert iface_node.chunk_id in result
    assert enum_node.chunk_id in result


def test_link_traverser_i_prefix_still_works():
    """I-prefix names still work (backward compatibility with existing
    behavior)."""
    graph = _make_enum_link_test_graph()
    traverser = LinkTraverser()

    # Start from a method that returns INode
    method_node = next(
        n for n in graph.nodes.values()
        if n.kind == "method" and n.metadata.get("function_name") == "Create"
    )
    result = traverser.traverse([method_node.chunk_id], graph, max_depth=2)

    iface_node = next(
        n for n in graph.nodes.values()
        if n.kind == "interface" and n.metadata.get("interface_name") == "INode"
    )
    assert method_node.chunk_id in result
    assert iface_node.chunk_id in result


def test_link_traverser_unknown_name_ignored():
    """Names that don't match any interface or enum are silently ignored
    (no crash, skipped)."""
    graph = _make_enum_link_test_graph()
    traverser = LinkTraverser()

    # Add content with a reference to a non-existent type
    iface_node = next(
        n for n in graph.nodes.values()
        if n.kind == "interface" and n.metadata.get("interface_name") == "IElement"
    )
    iface_node.content = "IElement references INonExistentType"

    result = traverser.traverse([iface_node.chunk_id], graph, max_depth=2)
    assert iface_node.chunk_id in result
    # No additional nodes should be added (unknown type silently skipped)
    assert len(result) == 1


def test_link_traverser_max_depth_enum():
    """max_depth limit applies to enum-originated traversal (depth 1 follows
    direct refs)."""
    graph = _make_enum_link_test_graph()
    traverser = LinkTraverser()

    iface_node = next(
        n for n in graph.nodes.values()
        if n.kind == "interface" and n.metadata.get("interface_name") == "INode"
    )
    enum_node = next(n for n in graph.nodes.values() if n.kind == "enum")

    # max_depth=1 follows direct refs
    result = traverser.traverse([iface_node.chunk_id], graph, max_depth=1)
    assert iface_node.chunk_id in result
    assert enum_node.chunk_id in result


def test_link_traverser_max_depth_zero():
    """max_depth=0 returns only starting nodes."""
    graph = _make_enum_link_test_graph()
    traverser = LinkTraverser()

    # Use a node with no references in its content (enum_value)
    ev_node = next(n for n in graph.nodes.values() if n.kind == "enum_value")
    result = traverser.traverse([ev_node.chunk_id], graph, max_depth=0)
    assert result == [ev_node.chunk_id]


def test_link_traverser_mixed_ie_refs():
    """Mix of I-prefix and E-prefix references are both followed in the
    same traversal."""
    graph = _make_enum_link_test_graph()
    traverser = LinkTraverser()

    # The Create method node references both EMaterialType (E-prefix)
    # and INode (I-prefix) in its content
    method_node = next(
        n for n in graph.nodes.values()
        if n.kind == "method" and n.metadata.get("function_name") == "Create"
    )
    result = traverser.traverse([method_node.chunk_id], graph, max_depth=2)

    iface_node = next(
        n for n in graph.nodes.values()
        if n.kind == "interface" and n.metadata.get("interface_name") == "INode"
    )
    enum_node = next(n for n in graph.nodes.values() if n.kind == "enum")

    assert method_node.chunk_id in result
    assert iface_node.chunk_id in result
    assert enum_node.chunk_id in result


def test_link_traverser_no_circular_refs():
    """No circular-reference infinite loops (depth limit + visited set)."""
    graph = _make_enum_link_test_graph()
    traverser = LinkTraverser()

    # Make EMaterialType's content reference back to INode
    enum_node = next(n for n in graph.nodes.values() if n.kind == "enum")
    enum_node.content = "Enum EMaterialType: Wood, Steel (see INode)"

    iface_node = next(
        n for n in graph.nodes.values()
        if n.kind == "interface" and n.metadata.get("interface_name") == "INode"
    )

    result = traverser.traverse([iface_node.chunk_id], graph, max_depth=5)
    # No duplicates
    assert len(result) == len(set(result))
    assert iface_node.chunk_id in result
    assert enum_node.chunk_id in result


def test_link_traverser_enum_resolution_order():
    """Enum name resolution checks interface_name_to_id first, then
    enum_name_to_id — same resolution order as the source code."""
    builder = ChunkGraphBuilder()
    # Create an interface with the same name as an enum to test priority
    iface_material = APIInterface(
        name="EMaterialType",
        description="Interface for material types",
        methods=[APIFunction(name="GetName", return_type="string")],
    )
    iface_test = APIInterface(
        name="ITest",
        description="Test interface",
        methods=[
            APIFunction(
                name="DoIt", return_type="void",
                parameters=[APIParameter(name="mat",
                                         type_annotation="EMaterialType")],
            ),
        ],
    )
    enum_material = APIEnum(
        name="EMaterialType",
        description="Material types enum",
        values=[APIEnumValue(name="Wood", value=0)],
    )
    graph = builder.build(
        interfaces=[iface_material, iface_test],
        enums=[enum_material],
        source_doc="test",
    )
    # Populate content
    for node in graph.nodes.values():
        meta = node.metadata
        if node.kind == "interface":
            iname = meta.get("interface_name", "")
            if iname == "ITest":
                node.content = "ITest with EMaterialType reference"
            else:
                node.content = f"Interface {iname}"
        elif node.kind == "enum":
            node.content = f"Enum {meta.get('type_name', '')}"

    traverser = LinkTraverser()
    test_node = next(
        n for n in graph.nodes.values()
        if n.kind == "interface" and n.metadata.get("interface_name") == "ITest"
    )
    result = traverser.traverse([test_node.chunk_id], graph, max_depth=2)

    # interface_name_to_id is checked first, so the INTERFACE named
    # "EMaterialType" should be followed, not the enum
    iface_material_node = next(
        n for n in graph.nodes.values()
        if n.kind == "interface" and n.metadata.get("interface_name") == "EMaterialType"
    )
    assert iface_material_node.chunk_id in result, (
        "Interface should take priority over enum with same name"
    )


# ---------------------------------------------------------------------------
# ParentExpander
# ---------------------------------------------------------------------------


def test_parent_expander_from_parameter():
    """Expanding from a parameter node includes parent method and grandparent interface."""
    graph = _make_link_test_graph()
    param_node = next((n for n in graph.nodes.values() if n.kind == "parameter"), None)
    if param_node is None:
        pytest.skip("No parameter nodes in test graph")

    expander = ParentExpander()
    result = expander.expand([param_node.chunk_id], graph, max_parents=2)

    assert param_node.chunk_id in result
    assert param_node.parent_id in result  # method is included

    # Grandparent (interface) should be in result if max_parents >= 2
    method_node = graph.nodes[param_node.parent_id]
    if method_node and method_node.parent_id:
        assert method_node.parent_id in result


def test_parent_expander_max_parents():
    """max_parents limits how many ancestor levels are included."""
    graph = _make_link_test_graph()
    param_node = next((n for n in graph.nodes.values() if n.kind == "parameter"), None)
    if param_node is None:
        pytest.skip("No parameter nodes in test graph")

    expander = ParentExpander()
    with_min = expander.expand([param_node.chunk_id], graph, max_parents=0)

    # With max_parents=0, only the original IDs are returned
    assert param_node.chunk_id in with_min
    if param_node.parent_id:
        assert param_node.parent_id not in with_min  # parent not included


def test_parent_expander_empty_input():
    """Empty input returns empty list."""
    graph = _make_link_test_graph()
    expander = ParentExpander()
    result = expander.expand([], graph)
    assert result == []


def test_parent_expander_deduplicates():
    """Parent expander does not duplicate IDs."""
    graph = _make_sample_graph()
    root_ids = list(graph.root_node_ids)
    expander = ParentExpander()
    # Expand from root nodes (they're already top-level)
    result = expander.expand(root_ids, graph)
    assert len(result) == len(set(result))  # no duplicates
    for rid in root_ids:
        assert rid in result
