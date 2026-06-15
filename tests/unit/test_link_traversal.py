"""
Unit tests for _expand_with_links() link traversal logic.

Tests the expansion of retrieval results via 1-hop link traversal:
forward links, backlinks, score decay, deduplication, and capping.

Uses mocking for the async database session — no real DB needed.
"""

from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.routes.query._retrieval import _expand_with_links, retrieve_chunks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_chunk(
    chunk_id: str,
    content: str = "",
    metadata: Optional[dict] = None,
    document_id: str = "doc-1",
    chunk_index: int = 0,
    embedding: Optional[list[float]] = None,
) -> SimpleNamespace:
    """Create a minimal mock Chunk-like object.

    The real SQLAlchemy Chunk model has ``chunk_metadata`` as the column name,
    exposed as ``.chunk_metadata`` on instances, plus ``document_id`` and
    ``chunk_index`` attributes used by the link-traversal query.
    """
    return SimpleNamespace(
        id=chunk_id,
        content=content,
        chunk_metadata=metadata or {},
        document_id=document_id,
        chunk_index=chunk_index,
        embedding=embedding,
    )


def mock_db(*, linked_chunks: Optional[list] = None) -> AsyncMock:
    """Build a mock ``AsyncSession`` whose ``execute()`` returns linked chunks.

    ``await db.execute(...)`` is wired via an ``AsyncMock`` so the result
    is properly awaitable.

    Parameters
    ----------
    linked_chunks:
        What ``result.scalars().all()`` should return.
        If ``None``, ``execute`` will raise ``NotImplementedError`` so that
        tests expecting *no* DB call can fail loudly.
    """
    db = AsyncMock(spec=["execute"])

    if linked_chunks is not None:
        async def _execute_impl(*args, **kwargs):
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = linked_chunks
            return mock_result

        db.execute = AsyncMock(side_effect=_execute_impl)
    else:
        db.execute.side_effect = NotImplementedError(
            "This test should not call db.execute"
        )

    return db


def make_link(target_chunk_ids: list[str]) -> dict:
    return {"target_chunk_ids": target_chunk_ids}


def make_backlink(source_chunk_id: str) -> dict:
    return {"source_chunk_id": source_chunk_id}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

DECAY = 0.85


class TestExpandNoLinks:
    """Scenarios where no link traversal should happen."""

    @pytest.mark.asyncio
    async def test_empty_chunks(self):
        """Empty input → empty output."""
        result = await _expand_with_links([], AsyncMock())
        assert result == []

    @pytest.mark.asyncio
    async def test_no_links_key(self):
        """Metadata without 'links' or 'backlinks' keys → no expansion."""
        chunk = make_chunk("c1", "text", metadata={"irrelevant": True})
        db = mock_db()
        result = await _expand_with_links([(chunk, 0.9)], db)
        assert len(result) == 1
        assert result[0][0].id == "c1"

    @pytest.mark.asyncio
    async def test_empty_links_list(self):
        """Metadata with empty links/backlists lists → no expansion."""
        chunk = make_chunk("c1", "text", metadata={
            "links": [],
            "backlinks": [],
        })
        db = mock_db()
        result = await _expand_with_links([(chunk, 0.9)], db)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_none_links(self):
        """Metadata with links=None → no expansion (``or []`` handles it)."""
        chunk = make_chunk("c1", "text", metadata={"links": None, "backlinks": None})
        db = mock_db()
        result = await _expand_with_links([(chunk, 0.9)], db)
        assert len(result) == 1
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_target_ids(self):
        """Links with empty target_chunk_ids and backlink with empty source → no DB call."""
        chunk = make_chunk("c1", "text", metadata={
            "links": [{"target_chunk_ids": []}],
            "backlinks": [{"source_chunk_id": ""}],
        })
        db = mock_db()
        result = await _expand_with_links([(chunk, 0.9)], db)
        assert len(result) == 1
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_chunk_metadata_is_none(self):
        """``chunk_metadata`` is ``None`` → treated as empty dict → no expansion."""
        chunk = make_chunk("c1", "text", metadata=None)
        chunk.chunk_metadata = None  # explicit override
        db = mock_db()
        result = await _expand_with_links([(chunk, 0.9)], db)
        assert len(result) == 1
        db.execute.assert_not_called()


class TestForwardLinks:
    """Forward link traversal scenarios."""

    @pytest.mark.asyncio
    async def test_single_forward_link(self):
        """Single forward link → linked chunk appended with decayed score."""
        c1 = make_chunk("c1", "source", metadata={"links": [make_link(["c2"])]})
        c2 = make_chunk("c2", "linked")

        db = mock_db(linked_chunks=[c2])
        result = await _expand_with_links([(c1, 0.9)], db)

        assert len(result) == 2
        # Sorted by score descending → c1 then c2
        assert result[0][0].id == "c1"
        assert result[0][1] == pytest.approx(0.9)
        assert result[1][0].id == "c2"
        assert result[1][1] == pytest.approx(0.9 * DECAY)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_forward_links(self):
        """Multiple target_chunk_ids from a single link ref → all fetched."""
        c1 = make_chunk("c1", "source", metadata={"links": [make_link(["c2", "c3"])]})
        c2 = make_chunk("c2", "linked-2")
        c3 = make_chunk("c3", "linked-3")

        db = mock_db(linked_chunks=[c2, c3])
        # expansion_factor=3 ensures all linked chunks fit under the cap
        result = await _expand_with_links([(c1, 0.9)], db, expansion_factor=3)

        assert len(result) == 3
        linked_ids = {c.id for c, _ in result}
        assert "c2" in linked_ids
        assert "c3" in linked_ids

    @pytest.mark.asyncio
    async def test_multiple_link_objects(self):
        """Multiple link objects in the links array → all targets collected."""
        c1 = make_chunk("c1", "src", metadata={
            "links": [make_link(["c2"]), make_link(["c3"])],
        })
        c2 = make_chunk("c2", "linked-2")
        c3 = make_chunk("c3", "linked-3")

        db = mock_db(linked_chunks=[c2, c3])
        # expansion_factor=3 ensures both linked chunks fit under the cap
        result = await _expand_with_links([(c1, 0.9)], db, expansion_factor=3)
        assert len(result) == 3


class TestBacklinks:
    """Backlink traversal scenarios."""

    @pytest.mark.asyncio
    async def test_single_backlink(self):
        """Backlink present → source chunk added."""
        c1 = make_chunk("c1", "current", metadata={"backlinks": [make_backlink("c0")]})
        c0 = make_chunk("c0", "backlink-source")

        db = mock_db(linked_chunks=[c0])
        result = await _expand_with_links([(c1, 0.9)], db)

        assert len(result) == 2
        assert "c0" in {c.id for c, _ in result}
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_backlinks(self):
        """Multiple backlinks → all source chunks added."""
        c1 = make_chunk("c1", "current", metadata={
            "backlinks": [make_backlink("c0_a"), make_backlink("c0_b")],
        })
        c0_a = make_chunk("c0_a", "backlink-a")
        c0_b = make_chunk("c0_b", "backlink-b")

        db = mock_db(linked_chunks=[c0_a, c0_b])
        # expansion_factor=3 ensures both source chunks fit under the cap
        result = await _expand_with_links([(c1, 0.9)], db, expansion_factor=3)
        assert len(result) == 3


class TestMixedLinks:
    """Tests mixing forward links and backlinks."""

    @pytest.mark.asyncio
    async def test_forward_and_backlinks_together(self):
        """Both links and backlinks present → both targets fetched in one query."""
        c1 = make_chunk("c1", "mid", metadata={
            "links": [make_link(["c2"])],
            "backlinks": [make_backlink("c0")],
        })
        c0 = make_chunk("c0", "backlink-source")
        c2 = make_chunk("c2", "forward-target")

        db = mock_db(linked_chunks=[c0, c2])
        # expansion_factor=3 ensures both linked chunks fit under the cap
        result = await _expand_with_links([(c1, 0.9)], db, expansion_factor=3)
    
        assert len(result) == 3
        assert "c0" in {c.id for c, _ in result}
        assert "c2" in {c.id for c, _ in result}
        # Only one DB query (all target IDs batched together)
        db.execute.assert_awaited_once()


class TestDeduplication:
    """Ensure no duplicate chunks appear in the expanded results."""

    @pytest.mark.asyncio
    async def test_linked_chunk_already_in_original(self):
        """Linked chunk already present in original results → not duplicated.

        The original score should be kept (higher) over the linked decayed score.
        """
        c1 = make_chunk("c1", "original", metadata={"links": [make_link(["c2"])]})
        c2 = make_chunk("c2", "both")

        chunks = [(c1, 0.9), (c2, 0.8)]
        db = mock_db(linked_chunks=[c2])
        result = await _expand_with_links(chunks, db)

        # c2 appears only once (the original entry, score=0.8)
        assert len(result) == 2
        c2_entries = [(c, s) for c, s in result if c.id == "c2"]
        assert len(c2_entries) == 1
        # The original score (0.8) is higher than the decayed (0.9*0.85=0.765)
        assert c2_entries[0][1] == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_duplicate_between_two_source_chunks(self):
        """Two source chunks linking to the same chunk → keep higher decayed score."""
        c1 = make_chunk("c1", "high-score", metadata={"links": [make_link(["c3"])]})
        c2 = make_chunk("c2", "low-score", metadata={"links": [make_link(["c3"])]})
        c3 = make_chunk("c3", "linked-by-both")

        db = mock_db(linked_chunks=[c3])
        result = await _expand_with_links([(c1, 0.9), (c2, 0.5)], db)

        assert len(result) == 3
        c3_entry = [(c, s) for c, s in result if c.id == "c3"]
        assert len(c3_entry) == 1
        # Expect score from higher source: 0.9 * decay
        assert c3_entry[0][1] == pytest.approx(0.9 * DECAY)


class TestScoreDecay:
    """Score-decay behaviour."""

    @pytest.mark.asyncio
    async def test_default_decay_factor(self):
        """Default decay factor of 0.85 is applied."""
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["c2"])]})
        c2 = make_chunk("c2", "linked")

        db = mock_db(linked_chunks=[c2])
        result = await _expand_with_links([(c1, 0.9)], db)

        c2_score = next(s for c, s in result if c.id == "c2")
        assert c2_score == pytest.approx(0.9 * 0.85)

    @pytest.mark.asyncio
    async def test_custom_decay_factor(self):
        """Custom decay factor is honoured."""
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["c2"])]})
        c2 = make_chunk("c2", "linked")

        db = mock_db(linked_chunks=[c2])
        result = await _expand_with_links([(c1, 0.9)], db, decay_factor=0.5)

        c2_score = next(s for c, s in result if c.id == "c2")
        assert c2_score == pytest.approx(0.9 * 0.5)

    @pytest.mark.asyncio
    async def test_no_decay_factor(self):
        """Decay factor of 1.0 → no score penalty for linked chunks."""
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["c2"])]})
        c2 = make_chunk("c2", "linked")

        db = mock_db(linked_chunks=[c2])
        result = await _expand_with_links([(c1, 0.9)], db, decay_factor=1.0)

        c2_score = next(s for c, s in result if c.id == "c2")
        assert c2_score == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_zero_decay_factor(self):
        """Zero decay factor → linked chunk gets score 0.0 (lowest sorting)."""
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["c2"])]})
        c2 = make_chunk("c2", "linked")

        db = mock_db(linked_chunks=[c2])
        result = await _expand_with_links([(c1, 0.9)], db, decay_factor=0.0)

        assert len(result) == 2
        c2_entry = next((c, s) for c, s in result if c.id == "c2")
        assert c2_entry[1] == pytest.approx(0.0)


class TestExpansionCap:
    """Expansion factor capping behaviour."""

    @pytest.mark.asyncio
    async def test_default_expansion_factor_cap(self):
        """Default expansion_factor=2 → max 2*len(original) results.

        1 original chunk → max 2 results (1 original + 1 linked).
        """
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["c2", "c3", "c4"])]})
        c2 = make_chunk("c2", "linked-2")
        c3 = make_chunk("c3", "linked-3")
        c4 = make_chunk("c4", "linked-4")

        db = mock_db(linked_chunks=[c2, c3, c4])
        result = await _expand_with_links([(c1, 0.9)], db)

        # len(chunks)=1, expansion_factor=2 → max_results=2
        # Sorted by score: c1 (0.9) first, then one linked chunk
        assert len(result) == 2
        assert result[0][0].id == "c1"

    @pytest.mark.asyncio
    async def test_custom_expansion_factor(self):
        """Custom expansion_factor of 4 → allow up to 4× results.

        With 1 original + 3 linked = 4 total, all fit under the cap
        since max_results = 1 * 4 = 4.
        """
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["c2", "c3", "c4"])]})
        c2 = make_chunk("c2", "linked-2")
        c3 = make_chunk("c3", "linked-3")
        c4 = make_chunk("c4", "linked-4")

        db = mock_db(linked_chunks=[c2, c3, c4])
        result = await _expand_with_links([(c1, 0.9)], db, expansion_factor=4)

        assert len(result) == 4  # 1 original + 3 linked (all fit under cap)

    @pytest.mark.asyncio
    async def test_no_expansion_factor(self):
        """expansion_factor=1 → no linked chunks added (cap = original count)."""
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["c2"])]})
        c2 = make_chunk("c2", "linked")

        db = mock_db(linked_chunks=[c2])
        result = await _expand_with_links([(c1, 0.9)], db, expansion_factor=1)

        # max_results = 1 * 1 = 1 → only original chunk fits
        assert len(result) == 1
        assert result[0][0].id == "c1"

    @pytest.mark.asyncio
    async def test_large_expansion_does_not_duplicate(self):
        """Even with large expansion factor, already-seen chunks are not duplicated."""
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["c2"])]})
        c2 = make_chunk("c2", "both")

        db = mock_db(linked_chunks=[c2])
        result = await _expand_with_links([(c1, 0.9), (c2, 0.8)], db, expansion_factor=10)

        assert len(result) == 2  # no duplicate


class TestDBInteraction:
    """Database interaction edge cases."""

    @pytest.mark.asyncio
    async def test_db_failure_continues(self):
        """DB exception during linked chunk fetch → original chunks are kept."""
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["c2"])]})

        db = AsyncMock(spec=["execute"])
        db.execute.side_effect = Exception("Connection lost")

        result = await _expand_with_links([(c1, 0.9)], db)
        assert len(result) == 1
        assert result[0][0].id == "c1"

    @pytest.mark.asyncio
    async def test_db_returns_empty_list(self):
        """DB returns no results for linked IDs → no linked chunks added."""
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["nonexistent"])]})

        db = mock_db(linked_chunks=[])
        result = await _expand_with_links([(c1, 0.9)], db)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_multiple_chunks_each_with_links(self):
        """Multiple original chunks with links → all targets fetched in one query."""
        c1 = make_chunk("c1", "first", metadata={"links": [make_link(["c3"])]})
        c2 = make_chunk("c2", "second", metadata={"links": [make_link(["c4"])]})
        c3 = make_chunk("c3", "linked-3")
        c4 = make_chunk("c4", "linked-4")

        db = AsyncMock(spec=["execute"])

        # Return all linked chunks in a single call (the implementation
        # now batches all target refs into one or_() query).
        async def _execute_impl(*args, **kwargs):
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [c3, c4]
            return mock_result

        db.execute = AsyncMock(side_effect=_execute_impl)

        # expansion_factor=3 so both linked chunks fit: max = 2 * 3 = 6
        result = await _expand_with_links(
            [(c1, 0.9), (c2, 0.8)], db, expansion_factor=3
        )

        assert len(result) == 4
        # Only one query now (batched or_ with both targets)
        assert db.execute.await_count == 1


class TestResultOrdering:
    """Result ordering and marking."""

    @pytest.mark.asyncio
    async def test_sorted_by_score_descending(self):
        """Expanded results are sorted by score descending."""
        c1 = make_chunk("c1", "high", metadata={"links": [make_link(["c3"])]})
        c2 = make_chunk("c2", "medium")
        c3 = make_chunk("c3", "linked-decayed")

        db = mock_db(linked_chunks=[c3])
        result = await _expand_with_links([(c1, 0.9), (c2, 0.7)], db)

        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_linked_chunks_marked(self):
        """Each linked chunk gets ``_retrieved_via`` set to ``'link_traversal'``."""
        c1 = make_chunk("c1", "src", metadata={"links": [make_link(["c2"])]})
        c2 = make_chunk("c2", "linked")

        db = mock_db(linked_chunks=[c2])
        result = await _expand_with_links([(c1, 0.9)], db)

        linked = [c for c, _ in result if c.id == "c2"]
        assert len(linked) == 1
        assert hasattr(linked[0], "_retrieved_via")
        assert linked[0]._retrieved_via == "link_traversal"


class TestRetrieveChunksSignature:
    """Verify that ``retrieve_chunks`` accepts the new link-traversal parameters."""

    def test_has_link_decay_factor_param(self):
        """``retrieve_chunks`` accepts ``link_decay_factor``."""
        import inspect
        sig = inspect.signature(retrieve_chunks)
        assert "link_decay_factor" in sig.parameters

    def test_has_link_expansion_factor_param(self):
        """``retrieve_chunks`` accepts ``link_expansion_factor``."""
        import inspect
        sig = inspect.signature(retrieve_chunks)
        assert "link_expansion_factor" in sig.parameters

    def test_link_decay_factor_default(self):
        """``link_decay_factor`` defaults to 0.85."""
        import inspect
        sig = inspect.signature(retrieve_chunks)
        assert sig.parameters["link_decay_factor"].default == 0.85

    def test_link_expansion_factor_default(self):
        """``link_expansion_factor`` defaults to 2."""
        import inspect
        sig = inspect.signature(retrieve_chunks)
        assert sig.parameters["link_expansion_factor"].default == 2


# ---------------------------------------------------------------------------
# retrieve_chunks unit tests (mocked DB + embedder)
# ---------------------------------------------------------------------------


class TestRetrieveChunksNoneEmbedding:
    """Chunks with ``embedding=None`` are skipped by ``retrieve_chunks``."""

    @pytest.mark.asyncio
    async def test_skip_chunks_with_none_embedding(self):
        """Chunks with ``embedding=None`` are excluded from results."""
        c1 = make_chunk("c1", "text1", embedding=[0.1, 0.2, 0.3])
        c2 = make_chunk("c2", "text2", embedding=None)
        c3 = make_chunk("c3", "text3", embedding=[0.4, 0.5, 0.6])

        docs = [MagicMock()]
        mock_doc_result = MagicMock()
        mock_doc_result.scalars.return_value.all.return_value = docs
        mock_chunk_result = MagicMock()
        mock_chunk_result.scalars.return_value.all.return_value = [c1, c2, c3]

        db = AsyncMock(spec=["execute"])
        db.execute = AsyncMock(side_effect=[mock_doc_result, mock_chunk_result])

        mock_embedder = AsyncMock()
        mock_embedder.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])

        mock_settings = MagicMock()
        mock_settings.min_relevance_score = 0.0

        with (
            patch("src.domain.services.embedding.get_embedder",
                  return_value=mock_embedder),
            patch("src.api.routes.query._retrieval.get_settings",
                  return_value=mock_settings),
        ):
            result = await retrieve_chunks(
                db=db,
                user_id="user-1",
                document_ids=["doc-1"],
                question="test question",
                top_k=10,
            )

        # c2 (embedding=None) should be skipped; c1 and c3 should be present
        result_ids = [c.id for c, _ in result]
        assert "c2" not in result_ids, "Chunk with None embedding was included"
        assert "c1" in result_ids
        assert "c3" in result_ids

    @pytest.mark.asyncio
    async def test_all_embeddings_none_returns_empty(self):
        """When all chunks have ``embedding=None``, an empty list is returned."""
        c1 = make_chunk("c1", "text1", embedding=None)
        c2 = make_chunk("c2", "text2", embedding=None)

        docs = [MagicMock()]
        mock_doc_result = MagicMock()
        mock_doc_result.scalars.return_value.all.return_value = docs
        mock_chunk_result = MagicMock()
        mock_chunk_result.scalars.return_value.all.return_value = [c1, c2]

        db = AsyncMock(spec=["execute"])
        db.execute = AsyncMock(side_effect=[mock_doc_result, mock_chunk_result])

        mock_embedder = AsyncMock()
        mock_embedder.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])

        mock_settings = MagicMock()
        mock_settings.min_relevance_score = 0.0

        with (
            patch("src.domain.services.embedding.get_embedder",
                  return_value=mock_embedder),
            patch("src.api.routes.query._retrieval.get_settings",
                  return_value=mock_settings),
        ):
            result = await retrieve_chunks(
                db=db,
                user_id="user-1",
                document_ids=["doc-1"],
                question="test question",
                top_k=10,
            )

        assert result == []


class TestRetrieveChunksMinRelevanceScore:
    """``min_relevance_score`` filtering in ``retrieve_chunks``."""

    @pytest.mark.asyncio
    async def test_filter_below_threshold(self):
        """Chunks with scores below ``min_relevance_score`` are excluded."""
        c1 = make_chunk("c1", "text1", embedding=[0.1, 0.2, 0.3])  # score = 0.14
        c2 = make_chunk("c2", "text2", embedding=[0.4, 0.5, 0.6])  # score = 0.32

        docs = [MagicMock()]
        mock_doc_result = MagicMock()
        mock_doc_result.scalars.return_value.all.return_value = docs
        mock_chunk_result = MagicMock()
        mock_chunk_result.scalars.return_value.all.return_value = [c1, c2]

        db = AsyncMock(spec=["execute"])
        db.execute = AsyncMock(side_effect=[mock_doc_result, mock_chunk_result])

        mock_embedder = AsyncMock()
        mock_embedder.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])

        mock_settings = MagicMock()
        mock_settings.min_relevance_score = 0.3  # c1=0.14 < 0.3, c2=0.32 >= 0.3

        with (
            patch("src.domain.services.embedding.get_embedder",
                  return_value=mock_embedder),
            patch("src.api.routes.query._retrieval.get_settings",
                  return_value=mock_settings),
        ):
            result = await retrieve_chunks(
                db=db,
                user_id="user-1",
                document_ids=["doc-1"],
                question="test question",
                top_k=10,
            )

        result_ids = [c.id for c, _ in result]
        assert "c1" not in result_ids, "c1 scored 0.14 but threshold is 0.3"
        assert "c2" in result_ids, "c2 scored 0.32 which is >= 0.3"

    @pytest.mark.asyncio
    async def test_all_below_threshold_returns_empty(self):
        """When no chunks pass ``min_relevance_score``, empty list is returned."""
        c1 = make_chunk("c1", "text1", embedding=[0.1, 0.2, 0.3])  # score = 0.14

        docs = [MagicMock()]
        mock_doc_result = MagicMock()
        mock_doc_result.scalars.return_value.all.return_value = docs
        mock_chunk_result = MagicMock()
        mock_chunk_result.scalars.return_value.all.return_value = [c1]

        db = AsyncMock(spec=["execute"])
        db.execute = AsyncMock(side_effect=[mock_doc_result, mock_chunk_result])

        mock_embedder = AsyncMock()
        mock_embedder.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])

        mock_settings = MagicMock()
        mock_settings.min_relevance_score = 0.5  # c1=0.14 is well below

        with (
            patch("src.domain.services.embedding.get_embedder",
                  return_value=mock_embedder),
            patch("src.api.routes.query._retrieval.get_settings",
                  return_value=mock_settings),
        ):
            result = await retrieve_chunks(
                db=db,
                user_id="user-1",
                document_ids=["doc-1"],
                question="test question",
                top_k=10,
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_equal_to_threshold_is_kept(self):
        """Scores exactly equal to ``min_relevance_score`` (>=) are kept."""
        c1 = make_chunk("c1", "text1", embedding=[0.1, 0.2, 0.3])  # score = 0.14

        docs = [MagicMock()]
        mock_doc_result = MagicMock()
        mock_doc_result.scalars.return_value.all.return_value = docs
        mock_chunk_result = MagicMock()
        mock_chunk_result.scalars.return_value.all.return_value = [c1]

        db = AsyncMock(spec=["execute"])
        db.execute = AsyncMock(side_effect=[mock_doc_result, mock_chunk_result])

        mock_embedder = AsyncMock()
        mock_embedder.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])

        # c1 score = 0.1*0.1 + 0.2*0.2 + 0.3*0.3 = 0.14
        mock_settings = MagicMock()
        mock_settings.min_relevance_score = 0.14

        with (
            patch("src.domain.services.embedding.get_embedder",
                  return_value=mock_embedder),
            patch("src.api.routes.query._retrieval.get_settings",
                  return_value=mock_settings),
        ):
            result = await retrieve_chunks(
                db=db,
                user_id="user-1",
                document_ids=["doc-1"],
                question="test question",
                top_k=10,
            )

        assert len(result) == 1
        assert result[0][0].id == "c1"
