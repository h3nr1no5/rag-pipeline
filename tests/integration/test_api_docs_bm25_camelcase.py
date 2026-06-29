"""Integration tests for BM25 camelCase tokenization in API doc retrieval.

Tests that the camelCase-aware ``_tokenize()`` method in
:class:`ApiBm25Index` correctly matches camelCase method names with
natural language queries (e.g. ``StartSelection`` → ``["start", "selection"]``).

Task 3.2 — Each test creates a small ``ChunkGraph`` with a single method,
builds a BM25 index, and verifies that natural-language queries containing
the camelCase-derived terms return the expected chunk.
"""

import pytest

from src.domain.rag.api_docs.chunking.builder import ChunkGraphBuilder
from src.domain.rag.api_docs.model.models import (
    APIFunction,
    APIInterface,
)
from src.domain.rag.api_docs.retrieval.bm25_index import ApiBm25Index

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_camelcase_graph(method_name: str, interface_name: str = "ITest"):
    """Create a small chunk graph with a single method for BM25 testing."""
    builder = ChunkGraphBuilder()
    iface = APIInterface(
        name=interface_name,
        description="Test interface",
        methods=[
            APIFunction(
                name=method_name,
                return_type="void",
                parameters=[],
            ),
        ],
        properties=[],
    )
    return builder.build(interfaces=[iface], source_doc="test-doc")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bm25_camelcase_method_match() -> None:
    """Method StartSelection is found when querying 'how to start selection'."""
    graph = _make_camelcase_graph("StartSelection")
    index = ApiBm25Index()
    index.add_graph(graph)

    method_node = next(n for n in graph.nodes.values() if n.kind == "method")
    results = index.search("how to start selection")
    result_ids = [rid for rid, _ in results]

    assert method_node.chunk_id in result_ids, (
        f"Expected StartSelection method ({method_node.chunk_id}) "
        f"in BM25 results: {result_ids}"
    )


@pytest.mark.asyncio
async def test_bm25_camelcase_acronym_match() -> None:
    """Method PDFParser is found when querying 'pdf parser'."""
    graph = _make_camelcase_graph("PDFParser")
    index = ApiBm25Index()
    index.add_graph(graph)

    method_node = next(n for n in graph.nodes.values() if n.kind == "method")
    results = index.search("pdf parser")
    result_ids = [rid for rid, _ in results]

    assert method_node.chunk_id in result_ids, (
        f"Expected PDFParser method ({method_node.chunk_id}) "
        f"in BM25 results: {result_ids}"
    )


@pytest.mark.asyncio
async def test_bm25_single_word_unchanged() -> None:
    """Method initialize is found when querying 'initialize' (backward compat)."""
    graph = _make_camelcase_graph("initialize")
    index = ApiBm25Index()
    index.add_graph(graph)

    method_node = next(n for n in graph.nodes.values() if n.kind == "method")
    results = index.search("initialize")
    result_ids = [rid for rid, _ in results]

    assert method_node.chunk_id in result_ids, (
        f"Expected initialize method ({method_node.chunk_id}) "
        f"in BM25 results: {result_ids}"
    )
