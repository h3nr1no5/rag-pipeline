"""Unit tests for API docs response type correctness.

Tests the fix for ``_query_fallback`` and ``_build_dspy_response`` to ensure:

- ``interface_name`` is included in ``relevant_types`` (not ``relevant_functions``)
- Fallback extraction works when DSPy returns empty ``relevant_functions``
  or ``relevant_types``
- Output is sorted alphabetically and deduplicated
- Empty metadata produces empty ``[]`` lists
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.rag.api_docs.chunking.builder import ChunkGraph
from src.domain.rag.api_docs.chunking.graph import ChunkNode
from src.domain.rag.api_docs.manager import ApiDocPipelineManager
from src.domain.rag.api_docs.retrieval.hybrid_retriever import (
    HybridRetriever,
)

# ===================================================================
# Helper factories
# ===================================================================


def _make_chunk_node(
    chunk_id: str,
    kind: str = "method",
    content: str = "Some content",
    interface_name: str = "",
    function_name: str = "",
    type_name: str = "",
    name: str = "",
) -> ChunkNode:
    """Build a ``ChunkNode`` with the requested metadata keys."""
    metadata: dict[str, str] = {}
    if interface_name:
        metadata["interface_name"] = interface_name
    if function_name:
        metadata["function_name"] = function_name
    if type_name:
        metadata["type_name"] = type_name
    if name:
        metadata["name"] = name
    return ChunkNode(
        chunk_id=chunk_id,
        kind=kind,
        content=content,
        metadata=metadata,
    )


def _make_graph(nodes: list[ChunkNode]) -> ChunkGraph:
    """Create a ``ChunkGraph`` and populate it with *nodes*."""
    graph = ChunkGraph()
    for node in nodes:
        graph.nodes[node.chunk_id] = node
        graph.root_node_ids.append(node.chunk_id)
    return graph


def _make_dspy_result(
    *,
    retrieved_chunks: list[tuple[str, float]] | None = None,
    relevant_functions: list[str] | None = None,
    relevant_types: list[str] | None = None,
    answer: str = "Test answer.",
    citations: list[str] | None = None,
    confidence: float = 0.85,
    rationale: str = "Test rationale.",
) -> dict:
    """Build a ``result`` dict matching the shape of ``APIDocRAG.forward()`` output."""
    return {
        "answer": answer,
        "citations": citations or [],
        "relevant_functions": relevant_functions or [],
        "relevant_types": relevant_types or [],
        "confidence": confidence,
        "rationale": rationale,
        "retrieved_chunks": retrieved_chunks or [],
        "primary_chunk_id": "",
        "assertions_passed": True,
        "used_fallback": False,
    }


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def manager():
    """Return an ``ApiDocPipelineManager`` with ``_generate_answer`` mocked out.

    The mocked method returns a canned answer so that ``_query_fallback`` does
    not attempt to contact a real LLM.
    """
    m = ApiDocPipelineManager()
    m._generate_answer = AsyncMock(return_value=("Generated answer.", []))
    return m


@pytest.fixture
def empty_graph():
    """Return a ``ChunkGraph`` with no nodes."""
    return ChunkGraph()


# ===================================================================
# _query_fallback tests  (tasks 3.1, 3.2, 3.6, 3.7)
# ===================================================================


class TestQueryFallbackTypes:
    """``_query_fallback()`` — relevant_types and relevant_functions extraction."""

    # ------------------------------------------------------------------
    # 3.1  — interface_name in relevant_types
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_interface_name_populates_relevant_types(self, manager, empty_graph):
        """``interface_name`` metadata contributes to ``relevant_types``."""
        # Arrange
        node = _make_chunk_node(chunk_id="c1", interface_name="IApplication")
        retriever = MagicMock(spec=HybridRetriever)
        retriever.retrieve = AsyncMock(return_value=[(node, 0.9)])

        # Act
        response = await manager._query_fallback(
            retriever=retriever,
            graph=empty_graph,
            query_text="query",
        )

        # Assert
        assert "IApplication" in response.relevant_types

    # ------------------------------------------------------------------
    # 3.2  — interface_name NOT in relevant_functions
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_interface_name_not_in_relevant_functions(self, manager, empty_graph):
        """``interface_name`` alone does NOT contribute to ``relevant_functions``."""
        # Arrange
        node = _make_chunk_node(chunk_id="c1", interface_name="IApplication")
        retriever = MagicMock(spec=HybridRetriever)
        retriever.retrieve = AsyncMock(return_value=[(node, 0.9)])

        # Act
        response = await manager._query_fallback(
            retriever=retriever,
            graph=empty_graph,
            query_text="query",
        )

        # Assert
        assert response.relevant_functions == []

    # ------------------------------------------------------------------
    # 3.6 part 1 — sorted + deduplicated output
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sorted_and_deduplicated(self, manager, empty_graph):
        """``relevant_functions`` and ``relevant_types`` are sorted and deduplicated."""
        # Arrange — multiple chunks with overlapping names, deliberately
        # unsorted chunk order
        nodes = [
            _make_chunk_node("c1", function_name="ZooMethod"),
            _make_chunk_node("c2", function_name="AlphaInit"),
            _make_chunk_node("c3", function_name="MidSort"),
            _make_chunk_node("c4", function_name="AlphaInit"),  # duplicate
            _make_chunk_node("c5", type_name="ZebraType"),
            _make_chunk_node("c6", type_name="AlphaType"),
            _make_chunk_node("c7", type_name="MidType"),
            _make_chunk_node("c8", type_name="ZebraType"),      # duplicate
        ]
        retriever = MagicMock(spec=HybridRetriever)
        retriever.retrieve = AsyncMock(
            return_value=[(n, 1.0 - i * 0.1) for i, n in enumerate(nodes)]
        )

        # Act
        response = await manager._query_fallback(
            retriever=retriever,
            graph=empty_graph,
            query_text="query",
        )

        # Assert — sorted ascending, no duplicates
        assert response.relevant_functions == ["AlphaInit", "MidSort", "ZooMethod"]
        assert response.relevant_types == ["AlphaType", "MidType", "ZebraType"]

    # ------------------------------------------------------------------
    # 3.7 part 1 — empty metadata → empty lists
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_metadata_returns_empty_lists(self, manager, empty_graph):
        """Chunks with no relevant metadata produce ``[]`` for both fields."""
        # Arrange
        node = _make_chunk_node("c1")  # no metadata at all
        retriever = MagicMock(spec=HybridRetriever)
        retriever.retrieve = AsyncMock(return_value=[(node, 0.9)])

        # Act
        response = await manager._query_fallback(
            retriever=retriever,
            graph=empty_graph,
            query_text="query",
        )

        # Assert
        assert response.relevant_functions == []
        assert response.relevant_types == []

    # ------------------------------------------------------------------
    # Additional scenarios from the spec
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_function_name_in_relevant_functions(self, manager, empty_graph):
        """``function_name`` contributes to ``relevant_functions``."""
        node = _make_chunk_node("c1", function_name="StartSelection")
        retriever = MagicMock(spec=HybridRetriever)
        retriever.retrieve = AsyncMock(return_value=[(node, 0.9)])

        response = await manager._query_fallback(
            retriever=retriever, graph=empty_graph, query_text="query",
        )

        assert response.relevant_functions == ["StartSelection"]

    @pytest.mark.asyncio
    async def test_name_fallback_in_relevant_functions(self, manager, empty_graph):
        """``name`` (without ``function_name``) contributes to ``relevant_functions``."""
        node = _make_chunk_node("c1", name="Initialize")
        retriever = MagicMock(spec=HybridRetriever)
        retriever.retrieve = AsyncMock(return_value=[(node, 0.9)])

        response = await manager._query_fallback(
            retriever=retriever, graph=empty_graph, query_text="query",
        )

        assert response.relevant_functions == ["Initialize"]

    @pytest.mark.asyncio
    async def test_type_name_in_relevant_types(self, manager, empty_graph):
        """``type_name`` contributes to ``relevant_types``."""
        node = _make_chunk_node("c1", type_name="MsoTriState")
        retriever = MagicMock(spec=HybridRetriever)
        retriever.retrieve = AsyncMock(return_value=[(node, 0.9)])

        response = await manager._query_fallback(
            retriever=retriever, graph=empty_graph, query_text="query",
        )

        assert response.relevant_types == ["MsoTriState"]

    @pytest.mark.asyncio
    async def test_both_type_and_interface_in_types(self, manager, empty_graph):
        """Both ``type_name`` and ``interface_name`` on same chunk populate types."""
        node = _make_chunk_node(
            "c1",
            type_name="MsoTriState",
            interface_name="IApplication",
        )
        retriever = MagicMock(spec=HybridRetriever)
        retriever.retrieve = AsyncMock(return_value=[(node, 0.9)])

        response = await manager._query_fallback(
            retriever=retriever, graph=empty_graph, query_text="query",
        )

        assert sorted(response.relevant_types) == ["IApplication", "MsoTriState"]

    @pytest.mark.asyncio
    async def test_no_results_returns_empty_lists(self, manager, empty_graph):
        """When no chunks are returned, both lists are ``[]``."""
        retriever = MagicMock(spec=HybridRetriever)
        retriever.retrieve = AsyncMock(return_value=[])

        response = await manager._query_fallback(
            retriever=retriever, graph=empty_graph, query_text="query",
        )

        assert response.relevant_functions == []
        assert response.relevant_types == []


# ===================================================================
# _build_dspy_response tests  (tasks 3.3-3.7)
# ===================================================================


class TestBuildDspyResponseTypes:
    """``_build_dspy_response()`` — fallback extraction when DSPy output is empty."""

    # ------------------------------------------------------------------
    # 3.3  — empty relevant_functions → fallback to sources
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_relevant_functions_triggers_fallback(self, manager):
        """When DSPy returns empty ``relevant_functions``, extract from sources."""
        # Arrange
        node = _make_chunk_node("c1", function_name="StartSelection")
        graph = _make_graph([node])
        result = _make_dspy_result(
            retrieved_chunks=[("c1", 0.9)],
            relevant_functions=[],
            relevant_types=["IType"],
        )

        # Act
        response = await manager._build_dspy_response(
            result=result, graph=graph, latency_ms=100,
            verification_enabled=False,
        )

        # Assert — functions extracted from source, types kept from DSPy
        assert response.relevant_functions == ["StartSelection"]
        assert response.relevant_types == ["IType"]

    # ------------------------------------------------------------------
    # 3.4  — non-empty DSPy output preserved unchanged
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_non_empty_dspy_output_preserved(self, manager):
        """Non-empty DSPy ``relevant_functions`` / ``relevant_types`` are kept."""
        # Arrange — sources have DIFFERENT values than DSPy output
        node = _make_chunk_node("c1", function_name="SourceFunc", type_name="SourceType")
        graph = _make_graph([node])
        result = _make_dspy_result(
            retrieved_chunks=[("c1", 0.9)],
            relevant_functions=["DSPyFunc"],
            relevant_types=["DSPyType"],
        )

        # Act
        response = await manager._build_dspy_response(
            result=result, graph=graph, latency_ms=100,
            verification_enabled=False,
        )

        # Assert — DSPy values are preserved, NOT replaced by source values
        assert response.relevant_functions == ["DSPyFunc"]
        assert response.relevant_types == ["DSPyType"]

    # ------------------------------------------------------------------
    # 3.5  — partial fallback (one field from DSPy, other from sources)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_partial_fallback_functions_from_dspy_types_from_sources(self, manager):
        """Only the empty DSPy field falls back; non-empty is preserved."""
        # Arrange — DSPy gives functions but empty types
        node = _make_chunk_node(
            "c1",
            function_name="SourceFunc",
            type_name="MsoTriState",
            interface_name="IApp",
        )
        graph = _make_graph([node])
        result = _make_dspy_result(
            retrieved_chunks=[("c1", 0.9)],
            relevant_functions=["DSPyFunc"],
            relevant_types=[],
        )

        # Act
        response = await manager._build_dspy_response(
            result=result, graph=graph, latency_ms=100,
            verification_enabled=False,
        )

        # Assert — functions from DSPy, types from sources
        assert response.relevant_functions == ["DSPyFunc"]
        assert sorted(response.relevant_types) == ["IApp", "MsoTriState"]

    @pytest.mark.asyncio
    async def test_partial_fallback_types_from_dspy_functions_from_sources(self, manager):
        """The symmetric case: DSPy types non-empty, functions empty → functions fall back."""
        # Arrange
        node = _make_chunk_node(
            "c1",
            function_name="SourceFunc",
            type_name="DSPyType",
        )
        graph = _make_graph([node])
        result = _make_dspy_result(
            retrieved_chunks=[("c1", 0.9)],
            relevant_functions=[],
            relevant_types=["DSPyType"],
        )

        # Act
        response = await manager._build_dspy_response(
            result=result, graph=graph, latency_ms=100,
            verification_enabled=False,
        )

        # Assert — types from DSPy, functions from sources
        assert response.relevant_functions == ["SourceFunc"]
        assert response.relevant_types == ["DSPyType"]

    # ------------------------------------------------------------------
    # 3.6 part 2 — sorted + deduplicated from fallback
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fallback_sorted_and_deduplicated(self, manager):
        """Fallback extraction produces sorted, deduplicated output."""
        # Arrange — sources with duplicates and unsorted names
        nodes = [
            _make_chunk_node("c1", function_name="ZooMethod", type_name="ZebraType"),
            _make_chunk_node("c2", function_name="AlphaInit", type_name="AlphaType"),
            _make_chunk_node("c3", function_name="MidSort",   type_name="MidType"),
            _make_chunk_node("c4", function_name="AlphaInit", type_name="ZebraType"),
        ]
        graph = _make_graph(nodes)
        result = _make_dspy_result(
            retrieved_chunks=[("c1", 0.9), ("c2", 0.8), ("c3", 0.7), ("c4", 0.6)],
            relevant_functions=[],
            relevant_types=[],
        )

        # Act
        response = await manager._build_dspy_response(
            result=result, graph=graph, latency_ms=100,
            verification_enabled=False,
        )

        # Assert
        assert response.relevant_functions == ["AlphaInit", "MidSort", "ZooMethod"]
        assert response.relevant_types == ["AlphaType", "MidType", "ZebraType"]

    # ------------------------------------------------------------------
    # 3.7 part 2 — empty metadata when DSPy also empty
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_metadata_and_empty_dspy_returns_empty_lists(self, manager):
        """When DSPy returns empty AND sources have no metadata, both are ``[]``."""
        # Arrange — node with no relevant metadata
        node = _make_chunk_node("c1")  # bare node, no metadata
        graph = _make_graph([node])
        result = _make_dspy_result(
            retrieved_chunks=[("c1", 0.9)],
            relevant_functions=[],
            relevant_types=[],
        )

        # Act
        response = await manager._build_dspy_response(
            result=result, graph=graph, latency_ms=100,
            verification_enabled=False,
        )

        # Assert
        assert response.relevant_functions == []
        assert response.relevant_types == []

    # ------------------------------------------------------------------
    # Edge cases for _build_dspy_response
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_interface_name_in_fallback_types(self, manager):
        """``interface_name`` from sources contributes to fallback ``relevant_types``."""
        # Arrange — source has interface_name, DSPy returned empty types
        node = _make_chunk_node("c1", interface_name="IApplication")
        graph = _make_graph([node])
        result = _make_dspy_result(
            retrieved_chunks=[("c1", 0.9)],
            relevant_functions=["DSPyFunc"],
            relevant_types=[],
        )

        # Act
        response = await manager._build_dspy_response(
            result=result, graph=graph, latency_ms=100,
            verification_enabled=False,
        )

        # Assert
        assert response.relevant_types == ["IApplication"]

    @pytest.mark.asyncio
    async def test_no_retrieved_chunks_keeps_dspy_empty_lists(self, manager):
        """No ``retrieved_chunks`` means no source fallback available."""
        # Arrange — empty retrieved_chunks
        graph = _make_graph([])  # empty graph
        result = _make_dspy_result(
            retrieved_chunks=[],
            relevant_functions=[],
            relevant_types=[],
        )

        # Act
        response = await manager._build_dspy_response(
            result=result, graph=graph, latency_ms=100,
            verification_enabled=False,
        )

        # Assert — nothing to fall back on
        assert response.relevant_functions == []
        assert response.relevant_types == []
