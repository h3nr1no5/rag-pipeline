"""Tests for ApiEmbeddingIndex.add_graph() format-skipping logic (Task 1.2).

Scenario 4a — pre-formatted content: when all graph nodes already have non-empty
``content``, ``format_graph()`` MUST NOT be called.
Scenario 4b — empty content: when graph nodes have empty ``content``,
``format_graph()`` MUST be called.

All tests use mocking to avoid FAISS / embedding-model dependencies.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.rag.api_docs.chunking.builder import ChunkGraph
from src.domain.rag.api_docs.chunking.graph import ChunkNode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_faiss_and_numpy():
    """Prevent real faiss / numpy imports inside ``add_graph()``.

    We patch ``sys.modules`` *before* the code under test runs so that
    the local ``import faiss`` / ``import numpy as np`` statements inside
    ``ApiEmbeddingIndex.add_graph()`` receive test doubles.
    """
    mock_faiss = MagicMock()
    mock_faiss.IndexFlatIP.return_value = MagicMock()

    mock_np = MagicMock()
    mock_np.array.return_value = MagicMock()
    mock_np.float32 = float  # sufficient for ``dtype=np.float32``

    with patch.dict("sys.modules", {"faiss": mock_faiss, "numpy": mock_np}):
        yield


@pytest.fixture
def embedding_index():
    """Return an ``ApiEmbeddingIndex`` whose embedder is replaced with a mock."""
    from src.domain.rag.api_docs.retrieval.embedding_index import ApiEmbeddingIndex

    index = ApiEmbeddingIndex()
    mock_embedder = AsyncMock()
    mock_embedder.get_dimension.return_value = 384
    mock_embedder.embed_texts.return_value = [[0.1, 0.2], [0.3, 0.4]]
    index._get_embedder = AsyncMock(return_value=mock_embedder)  # type: ignore[method-assign]
    return index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph(*content_values: str) -> ChunkGraph:
    """Build a ``ChunkGraph`` whose nodes carry the given ``content`` values."""
    graph = ChunkGraph()
    for i, content in enumerate(content_values):
        node = ChunkNode(
            chunk_id=f"test-node-{i}",
            kind="interface",
            level=0,
            source_doc="test",
            content=content,
        )
        graph.nodes[node.chunk_id] = node
    return graph


# ---------------------------------------------------------------------------
# Scenario 4a — pre-formatted content (format_graph SHOULD be skipped)
# ---------------------------------------------------------------------------


class TestPreFormattedContent:
    """format_graph() is skipped when all graph nodes have content populated."""

    @pytest.mark.asyncio
    async def test_skip_format_when_all_content_populated(self, embedding_index):
        """All nodes have non-empty content -> ``format_graph`` NOT called."""
        graph = _make_graph("Interface: Foo", "Method: bar")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter)

        formatter.format_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_node_with_content_skips_format(self, embedding_index):
        """A single node with content also skips formatting."""
        graph = _make_graph("Only one chunk")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter)

        formatter.format_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_many_nodes_all_populated_skips_format(self, embedding_index):
        """Several nodes, all with content -> format_graph not called."""
        graph = _make_graph("A", "B", "C", "D", "E")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter)

        formatter.format_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_content_with_only_whitespace_skips_format(self, embedding_index):
        """Whitespace-only content is truthy -> format_graph NOT called."""
        graph = _make_graph("   ", "\t\n")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter)

        formatter.format_graph.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 4b — empty content (format_graph SHOULD be called)
# ---------------------------------------------------------------------------


class TestEmptyContent:
    """format_graph() is called when any node has empty content."""

    @pytest.mark.asyncio
    async def test_call_format_when_all_content_empty(self, embedding_index):
        """All nodes have empty content -> ``format_graph`` IS called."""
        graph = _make_graph("", "")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter)

        formatter.format_graph.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_format_when_mixed_content(self, embedding_index):
        """Some nodes populated, some empty -> ``format_graph`` IS called."""
        graph = _make_graph("Has content", "", "Also has content")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter)

        formatter.format_graph.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_empty_node_triggers_format(self, embedding_index):
        """Even one empty node out of many triggers formatting."""
        graph = _make_graph("full", "full", "full", "")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter)

        formatter.format_graph.assert_called_once()

    @pytest.mark.asyncio
    async def test_format_receives_domain_objects(self, embedding_index):
        """When format_graph is called, domain object lists are forwarded."""
        graph = _make_graph("")
        formatter = MagicMock()

        interfaces = MagicMock()
        enums = MagicMock()
        error_codes = MagicMock()
        records = MagicMock()

        await embedding_index.add_graph(
            graph,
            formatter,
            interfaces=interfaces,
            enums=enums,
            error_codes=error_codes,
            records=records,
        )

        formatter.format_graph.assert_called_once_with(
            graph, interfaces, enums, error_codes, records=records,
        )

    @pytest.mark.asyncio
    async def test_format_without_domain_objects(self, embedding_index):
        """format_graph can be called with all-None domain objects."""
        graph = _make_graph("")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter)

        formatter.format_graph.assert_called_once_with(
            graph, None, None, None, records=None,
        )
