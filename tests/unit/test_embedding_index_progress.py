"""Tests for progress callback in ApiEmbeddingIndex.add_graph() (Task 2.4).

Scenarios:
1. Progress callback is invoked before model load and before batch encoding.
2. No callback when ``progress_callback=None`` (backward compatibility).

All tests use mocking to avoid FAISS / embedding-model dependencies.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_faiss_and_numpy():
    """Prevent real faiss / numpy imports inside ``add_graph()``."""
    mock_faiss = MagicMock()
    mock_faiss.IndexFlatIP.return_value = MagicMock()

    mock_np = MagicMock()
    mock_np.array.return_value = MagicMock()
    mock_np.float32 = float

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


def _make_graph(*content_values: str):
    """Build a minimal ``ChunkGraph`` with one node per content value."""
    from src.domain.rag.api_docs.chunking.builder import ChunkGraph
    from src.domain.rag.api_docs.chunking.graph import ChunkNode

    graph = ChunkGraph()
    for i, content in enumerate(content_values):
        node = ChunkNode(
            chunk_id=f"pn-{i}",
            kind="interface",
            level=0,
            source_doc="test",
            content=content,
        )
        graph.nodes[node.chunk_id] = node
    return graph


# ---------------------------------------------------------------------------
# Scenario 1 — progress callback invoked at correct stages
# ---------------------------------------------------------------------------


class TestProgressCallback:
    """Progress callback is invoked at the expected lifecycle points."""

    @pytest.mark.asyncio
    async def test_callback_called_with_loading_message(self, embedding_index):
        """Callback receives ``("indexing", "Formatting graph content…")``."""
        progress = AsyncMock()
        graph = _make_graph("Chunk A content", "Chunk B content")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter, progress_callback=progress)

        progress.report.assert_any_call("indexing", "Formatting graph content…")

    @pytest.mark.asyncio
    async def test_callback_called_with_embedding_message(self, embedding_index):
        """Callback receives ``("indexing", "Embedding N chunks…")``."""
        progress = AsyncMock()
        graph = _make_graph("Chunk A content", "Chunk B content")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter, progress_callback=progress)

        progress.report.assert_any_call("indexing", "Embedding 2 chunks…")

    @pytest.mark.asyncio
    async def test_callback_receives_both_messages(self, embedding_index):
        """Callback is called exactly twice for a populated graph."""
        progress = AsyncMock()
        graph = _make_graph("Chunk A content", "Chunk B content")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter, progress_callback=progress)

        assert progress.report.call_count == 2

    @pytest.mark.asyncio
    async def test_callback_message_order(self, embedding_index):
        """'Formatting graph' appears before 'Embedding N chunks'."""
        progress = AsyncMock()
        graph = _make_graph("Chunk A content", "Chunk B content")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter, progress_callback=progress)

        calls = [call.args for call in progress.report.call_args_list]
        assert calls == [
            ("indexing", "Formatting graph content…"),
            ("indexing", "Embedding 2 chunks…"),
        ]

    @pytest.mark.asyncio
    async def test_embedding_count_matches_non_empty_nodes(self, embedding_index):
        """The chunk count reflects only nodes with non-empty content."""
        progress = AsyncMock()
        # Two nodes have content, one is empty -> count should be 2
        graph = _make_graph("Content A", "", "Content B")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter, progress_callback=progress)

        progress.report.assert_any_call("indexing", "Embedding 2 chunks…")

    @pytest.mark.asyncio
    async def test_callback_not_called_when_no_content(self, embedding_index):
        """When all nodes are empty, the embedding message is skipped
        (the method returns early before the second progress call)."""
        progress = AsyncMock()
        graph = _make_graph("", "")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter, progress_callback=progress)

        # "Formatting graph content…" SHOULD still be called
        progress.report.assert_any_call("indexing", "Formatting graph content…")
        # But "Embedding N chunks" should NOT
        embed_calls = [
            call
            for call in progress.report.call_args_list
            if "Embedding" in call.args[1]
        ]
        assert len(embed_calls) == 0


# ---------------------------------------------------------------------------
# Scenario 2 — no callback (backward compatibility)
# ---------------------------------------------------------------------------


class TestNoCallback:
    """When ``progress_callback=None``, no progress is reported."""

    @pytest.mark.asyncio
    async def test_none_callback_does_not_raise(self, embedding_index):
        """``progress_callback=None`` should not raise."""
        graph = _make_graph("Some content")
        formatter = MagicMock()

        # Should not raise
        await embedding_index.add_graph(graph, formatter, progress_callback=None)

    @pytest.mark.asyncio
    async def test_none_callback_with_empty_graph(self, embedding_index):
        """``progress_callback=None`` with empty graph does not raise."""
        graph = _make_graph("", "")
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter, progress_callback=None)

    @pytest.mark.asyncio
    async def test_none_callback_large_graph(self, embedding_index):
        """``progress_callback=None`` with many nodes does not raise."""
        graph = _make_graph(*(f"content-{i}" for i in range(10)))
        formatter = MagicMock()

        await embedding_index.add_graph(graph, formatter, progress_callback=None)
