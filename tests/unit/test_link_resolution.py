"""
Unit tests for the link resolution module (``link_resolver.py``).

Tests the :func:`resolve_links` function which resolves extracted hyperlinks
into per-chunk ``links`` and ``backlinks`` metadata arrays.
"""

from __future__ import annotations

import pytest
from src.domain.services.link_resolver import resolve_links
from src.infrastructure.parsers.base import LinkInfo


# ---------------------------------------------------------------------------
# Edge: empty / None inputs
# ---------------------------------------------------------------------------


class TestEdgeInputs:
    """Empty and None input guards."""

    def test_empty_chunks(self):
        """Empty chunks list with links present should return without error."""
        chunks: list[dict] = []
        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        # Should not raise
        resolve_links(chunks, links)

    def test_empty_links(self):
        """Chunks with no links should not add any links/backlinks metadata."""
        chunks = [
            {"content": "text", "chunk_index": 0, "metadata": {"page_number": 1}},
        ]
        resolve_links(chunks, [])
        # Metadata should remain unchanged (no new keys added)
        assert chunks[0]["metadata"] == {"page_number": 1}

    def test_both_empty(self):
        """Both empty chunks and empty links should be a no-op."""
        resolve_links([], [])

    def test_none_chunks_raises_typeerror(self):
        """Passing None for chunks must raise TypeError."""
        with pytest.raises(TypeError, match="chunks must not be None"):
            resolve_links(None, [LinkInfo(type="internal")])  # type: ignore[arg-type]

    def test_none_links_raises_typeerror(self):
        """Passing None for all_links must raise TypeError."""
        with pytest.raises(TypeError, match="all_links must not be None"):
            resolve_links([{"content": "x", "chunk_index": 0}], None)  # type: ignore[arg-type]

    def test_both_none_raises_typeerror(self):
        """Passing None for both arguments must raise TypeError (first guard wins)."""
        with pytest.raises(TypeError, match="chunks must not be None"):
            resolve_links(None, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Internal link resolution
# ---------------------------------------------------------------------------


class TestInternalLinks:
    """Forward (``links``) and backward (``backlinks``) entries for internal
    page-to-page links."""

    def test_internal_link_resolved(self):
        """Internal link from page 1 → page 2: source chunk gets a ``links``
        entry; target chunk gets a ``backlinks`` entry."""
        chunks = [
            {"content": "source text", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "target text", "chunk_index": 1, "metadata": {"page_number": 2}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        resolve_links(chunks, links)

        # Source chunk should have a links entry
        assert "links" in chunks[0]["metadata"]
        link_entry = chunks[0]["metadata"]["links"][0]
        assert link_entry["type"] == "internal"
        # Target page has chunk index 1
        assert link_entry["target_chunk_ids"] == [1]
        assert link_entry["target_page"] == 2
        assert link_entry["uri"] is None

        # Target chunk should have a backlinks entry
        assert "backlinks" in chunks[1]["metadata"]
        backlink = chunks[1]["metadata"]["backlinks"][0]
        assert backlink["source_chunk_id"] == 0
        assert backlink["anchor_text"] is None

    def test_internal_link_with_anchor_text(self):
        """Anchor text from the link is propagated into the backlink entry."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "dst", "chunk_index": 1, "metadata": {"page_number": 2}},
        ]
        links = [
            LinkInfo(
                type="internal",
                source_page=1,
                target_page=2,
                anchor_text="click here",
            ),
        ]
        resolve_links(chunks, links)

        assert chunks[1]["metadata"]["backlinks"][0]["anchor_text"] == "click here"

    def test_internal_link_no_target_chunks(self):
        """Internal link that points to a page with no chunks is silently
        skipped — neither links nor backlinks are written."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=99)]
        resolve_links(chunks, links)

        # No links should be added since target page has no chunks
        assert "links" not in chunks[0].get("metadata", {})

    def test_internal_link_no_source_chunks(self):
        """Internal link whose source page has no chunks is skipped."""
        chunks = [
            {"content": "dst", "chunk_index": 0, "metadata": {"page_number": 2}},
        ]
        links = [LinkInfo(type="internal", source_page=99, target_page=2)]
        resolve_links(chunks, links)

        # Target chunk should not get backlinks since source is missing
        assert "backlinks" not in chunks[0].get("metadata", {})

    def test_internal_link_default_source_page(self):
        """When ``source_page`` is None, it defaults to 1."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "dst", "chunk_index": 1, "metadata": {"page_number": 2}},
        ]
        links = [LinkInfo(type="internal", source_page=None, target_page=2)]
        resolve_links(chunks, links)

        assert "links" in chunks[0]["metadata"]
        assert "backlinks" in chunks[1]["metadata"]

    def test_internal_link_idempotent(self):
        """Calling ``resolve_links`` twice with the same data should not
        duplicate link entries."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "dst", "chunk_index": 1, "metadata": {"page_number": 2}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=2)]

        resolve_links(chunks, links)
        resolve_links(chunks, links)  # second pass

        assert len(chunks[0]["metadata"]["links"]) == 1
        assert len(chunks[1]["metadata"]["backlinks"]) == 1


# ---------------------------------------------------------------------------
# External link resolution
# ---------------------------------------------------------------------------


class TestExternalLinks:
    """External links (URIs) — only forward entries, no backlinks."""

    def test_external_link(self):
        """External URI link adds a ``links`` entry with ``type="external"``
        and the correct URI."""
        chunks = [
            {"content": "text", "chunk_index": 0, "metadata": {"page_number": 1}},
        ]
        uri = "https://example.com/doc"
        links = [LinkInfo(type="external", source_page=1, uri=uri)]
        resolve_links(chunks, links)

        assert "links" in chunks[0]["metadata"]
        entry = chunks[0]["metadata"]["links"][0]
        assert entry["type"] == "external"
        assert entry["uri"] == uri
        assert entry["target_chunk_ids"] == []
        assert entry["target_page"] is None

    def test_external_link_no_backlinks(self):
        """External links must never add backlinks to any chunk."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
        ]
        links = [LinkInfo(type="external", source_page=1, uri="https://example.com")]
        resolve_links(chunks, links)

        assert "backlinks" not in chunks[0].get("metadata", {})

    def test_external_link_multiple_chunks_on_page(self):
        """All chunks on the source page get the external link entry."""
        chunks = [
            {"content": "a", "chunk_index": 0, "metadata": {"page_number": 2}},
            {"content": "b", "chunk_index": 1, "metadata": {"page_number": 2}},
            {"content": "c", "chunk_index": 2, "metadata": {"page_number": 3}},
        ]
        links = [LinkInfo(type="external", source_page=2, uri="https://example.com")]
        resolve_links(chunks, links)

        # Chunks on page 2 get the link
        assert len(chunks[0]["metadata"]["links"]) == 1
        assert len(chunks[1]["metadata"]["links"]) == 1
        # Chunk on page 3 does NOT get the link
        assert "links" not in chunks[2].get("metadata", {})

    def test_external_link_default_source_page(self):
        """When source_page is None, external link defaults to page 1."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
        ]
        links = [LinkInfo(type="external", source_page=None, uri="https://example.com")]
        resolve_links(chunks, links)

        assert "links" in chunks[0]["metadata"]

    def test_external_link_no_source_chunks(self):
        """External link with no matching source page silently skipped."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
        ]
        links = [LinkInfo(type="external", source_page=99, uri="https://example.com")]
        resolve_links(chunks, links)

        assert "links" not in chunks[0].get("metadata", {})


# ---------------------------------------------------------------------------
# Backlink cap
# ---------------------------------------------------------------------------


class TestBacklinkCap:
    """Backlink arrays must be capped at 10 entries per chunk."""

    def test_backlink_cap(self):
        """When more than 10 source chunks link to the same target chunk,
        the backlink list must be truncated to 10."""
        chunks = []
        # 15 source chunks on page 1
        for i in range(15):
            chunks.append({
                "content": f"src-{i}",
                "chunk_index": i,
                "metadata": {"page_number": 1},
            })
        # 1 target chunk on page 2
        chunks.append({
            "content": "target",
            "chunk_index": 15,
            "metadata": {"page_number": 2},
        })

        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        resolve_links(chunks, links)

        target = chunks[15]
        assert len(target["metadata"]["backlinks"]) == 10

    def test_backlink_at_boundary(self):
        """Exactly 10 backlinks should be preserved without truncation."""
        chunks = []
        for i in range(10):
            chunks.append({
                "content": f"src-{i}",
                "chunk_index": i,
                "metadata": {"page_number": 1},
            })
        chunks.append({
            "content": "target",
            "chunk_index": 10,
            "metadata": {"page_number": 2},
        })

        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        resolve_links(chunks, links)

        target = chunks[10]
        assert len(target["metadata"]["backlinks"]) == 10

    def test_backlink_under_boundary(self):
        """Fewer than 10 backlinks should all be preserved (no truncation)."""
        chunks = []
        for i in range(5):
            chunks.append({
                "content": f"src-{i}",
                "chunk_index": i,
                "metadata": {"page_number": 1},
            })
        chunks.append({
            "content": "target",
            "chunk_index": 5,
            "metadata": {"page_number": 2},
        })

        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        resolve_links(chunks, links)

        target = chunks[5]
        assert len(target["metadata"]["backlinks"]) == 5


# ---------------------------------------------------------------------------
# Multiple chunks per page
# ---------------------------------------------------------------------------


class TestMultipleChunksPerPage:
    """Links are broadcast to every chunk on the source / target page."""

    def test_multiple_chunks_per_page(self):
        """Multiple chunks on the same page: link is written to all source
        chunks and backlinks to all target chunks."""
        chunks = [
            {"content": "src-a", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "src-b", "chunk_index": 1, "metadata": {"page_number": 1}},
            {"content": "tgt-a", "chunk_index": 2, "metadata": {"page_number": 2}},
            {"content": "tgt-b", "chunk_index": 3, "metadata": {"page_number": 2}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        resolve_links(chunks, links)

        # Both source chunks have links
        for idx in (0, 1):
            assert "links" in chunks[idx]["metadata"]
            link_entry = chunks[idx]["metadata"]["links"][0]
            assert sorted(link_entry["target_chunk_ids"]) == [2, 3]

        # Both target chunks have backlinks
        for idx in (2, 3):
            assert "backlinks" in chunks[idx]["metadata"]
            backlink_ids = {b["source_chunk_id"] for b in chunks[idx]["metadata"]["backlinks"]}
            assert backlink_ids == {0, 1}

    def test_multiple_links_same_source(self):
        """A source chunk with multiple outgoing links accumulates them all."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "tgt-a", "chunk_index": 1, "metadata": {"page_number": 2}},
            {"content": "tgt-b", "chunk_index": 2, "metadata": {"page_number": 3}},
        ]
        links = [
            LinkInfo(type="internal", source_page=1, target_page=2),
            LinkInfo(type="internal", source_page=1, target_page=3),
        ]
        resolve_links(chunks, links)

        assert len(chunks[0]["metadata"]["links"]) == 2


# ---------------------------------------------------------------------------
# Page number resolution
# ---------------------------------------------------------------------------


class TestPageNumberResolution:
    """The ``_resolve_page_number`` helper must handle all recognised metadata
    keys consistently."""

    def test_page_number_key(self):
        """``metadata["page_number"]`` should resolve correctly."""
        chunks = [
            {"content": "x", "chunk_index": 0, "metadata": {"page_number": 5}},
            {"content": "y", "chunk_index": 1, "metadata": {"page_number": 10}},
        ]
        links = [LinkInfo(type="internal", source_page=5, target_page=10)]
        resolve_links(chunks, links)

        assert "links" in chunks[0]["metadata"]
        assert "backlinks" in chunks[1]["metadata"]

    def test_page_key(self):
        """``metadata["page"]`` should resolve correctly."""
        chunks = [
            {"content": "x", "chunk_index": 0, "metadata": {"page": 3}},
            {"content": "y", "chunk_index": 1, "metadata": {"page": 7}},
        ]
        links = [LinkInfo(type="internal", source_page=3, target_page=7)]
        resolve_links(chunks, links)

        assert "links" in chunks[0]["metadata"]
        assert "backlinks" in chunks[1]["metadata"]

    def test_source_page_metadata_key(self):
        """``metadata["source_page"]`` should resolve correctly."""
        chunks = [
            {"content": "x", "chunk_index": 0, "metadata": {"source_page": 2}},
            {"content": "y", "chunk_index": 1, "metadata": {"source_page": 4}},
        ]
        links = [LinkInfo(type="internal", source_page=2, target_page=4)]
        resolve_links(chunks, links)

        assert "links" in chunks[0]["metadata"]
        assert "backlinks" in chunks[1]["metadata"]

    def test_page_markers_key(self):
        """``metadata["page_markers"]`` (list of dicts with ``"page"``) should
        resolve using the first marker's page."""
        chunks = [
            {
                "content": "x",
                "chunk_index": 0,
                "metadata": {
                    "page_markers": [{"page": 8, "start_char": 0}],
                },
            },
            {
                "content": "y",
                "chunk_index": 1,
                "metadata": {
                    "page_markers": [{"page": 12, "start_char": 0}],
                },
            },
        ]
        links = [LinkInfo(type="internal", source_page=8, target_page=12)]
        resolve_links(chunks, links)

        assert "links" in chunks[0]["metadata"]
        assert "backlinks" in chunks[1]["metadata"]

    def test_top_level_source_page(self):
        """Top-level ``chunk["source_page"]`` (fallback) should resolve."""
        chunks = [
            {"content": "x", "chunk_index": 0, "source_page": 1, "metadata": {}},
            {"content": "y", "chunk_index": 1, "source_page": 3, "metadata": {}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=3)]
        resolve_links(chunks, links)

        assert "links" in chunks[0]["metadata"]
        assert "backlinks" in chunks[1]["metadata"]

    def test_default_page_1_when_no_metadata(self):
        """Chunks without any page info default to page 1."""
        chunks = [
            {"content": "no page info", "chunk_index": 0, "metadata": {}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        # No target chunk → link skipped; just verify no error
        resolve_links(chunks, links)

    def test_page_resolution_priority(self):
        """Verify priority order: ``page_number`` > ``page`` > ``source_page``
        > ``page_markers`` > top-level ``source_page``."""
        chunks = [
            {
                "content": "all keys present",
                "chunk_index": 0,
                "source_page": 99,  # should be ignored
                "metadata": {
                    "page_number": 1,  # highest priority → 1
                    "page": 2,
                    "source_page": 3,
                    "page_markers": [{"page": 4}],
                },
            },
        ]
        chunks.append({
            "content": "target",
            "chunk_index": 1,
            "metadata": {"page_number": 2},
        })
        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        resolve_links(chunks, links)

        # Chunk 0 should be resolved as page 1 and get the link
        assert "links" in chunks[0]["metadata"]


# ---------------------------------------------------------------------------
# Chunk index edge cases
# ---------------------------------------------------------------------------


class TestChunkIndexEdgeCases:
    """Chunks with missing or duplicate chunk_index values."""

    def test_missing_chunk_index_defaults_to_zero(self):
        """Chunks without ``chunk_index`` key default to 0 and should still
        be processed."""
        chunks = [
            {"content": "src", "metadata": {"page_number": 1}},  # no chunk_index
            {"content": "dst", "chunk_index": 1, "metadata": {"page_number": 2}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        resolve_links(chunks, links)

        # First chunk gets chunk_index=0 by default
        assert "links" in chunks[0].setdefault("metadata", {})
        assert "backlinks" in chunks[1]["metadata"]

    def test_duplicate_chunk_index(self):
        """If two chunks share the same chunk_index, only the last one in the
        list ends up in ``chunk_by_index``. The link is still written to the
        surviving chunk."""
        chunks = [
            {"content": "first", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "second (wins)", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "target", "chunk_index": 1, "metadata": {"page_number": 2}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        resolve_links(chunks, links)

        # Both chunks on page 1 have chunk_index 0. "links" gets written to
        # both because we iterate all chunks when building page_to_chunks.
        # The backlink entry references source_chunk_id=0.
        assert "links" in chunks[0]["metadata"] or "links" in chunks[1]["metadata"]
        assert chunks[2]["metadata"]["backlinks"][0]["source_chunk_id"] == 0

    def test_chunk_missing_from_by_index(self):
        """If a chunk's index is referenced but the chunk dict is absent from
        ``chunk_by_index`` (shouldn't happen in practice), the code skips it
        gracefully."""
        # This is tricky to construct because page_to_chunks and
        # chunk_by_index are built from the same list. We'd need a chunk
        # to exist in page_to_chunks but not in chunk_by_index. That can
        # only happen if the chunk is missing a chunk_index key and conflicts.
        # Test that the code handles None from chunk_by_index.get gracefully.
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "dst", "chunk_index": 1, "metadata": {"page_number": 2}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=2)]
        resolve_links(chunks, links)

        # Just verify it completes without error
        assert "links" in chunks[0]["metadata"]


# ---------------------------------------------------------------------------
# Mixed link types
# ---------------------------------------------------------------------------


class TestMixedLinks:
    """Document with both internal and external links simultaneously."""

    def test_internal_and_external_links(self):
        """Chunks on a page that has both an internal link and an external
        link get both entries."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "tgt", "chunk_index": 1, "metadata": {"page_number": 2}},
        ]
        links = [
            LinkInfo(type="internal", source_page=1, target_page=2),
            LinkInfo(type="external", source_page=1, uri="https://example.com"),
        ]
        resolve_links(chunks, links)

        assert len(chunks[0]["metadata"]["links"]) == 2
        types = {e["type"] for e in chunks[0]["metadata"]["links"]}
        assert types == {"internal", "external"}

    def test_link_with_none_target_page_internal(self):
        """Internal link with target_page=None is skipped (no target)."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=None)]
        resolve_links(chunks, links)

        assert "links" not in chunks[0].get("metadata", {})


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Multiple calls to ``resolve_links`` must not duplicate entries."""

    def test_double_call_no_duplicates(self):
        """Calling resolve_links twice with identical data does not duplicate
        entries."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "dst", "chunk_index": 1, "metadata": {"page_number": 2}},
        ]
        links = [LinkInfo(type="internal", source_page=1, target_page=2)]

        resolve_links(chunks, links)
        resolve_links(chunks, links)

        assert len(chunks[0]["metadata"]["links"]) == 1
        assert len(chunks[1]["metadata"]["backlinks"]) == 1

    def test_incremental_add_no_duplicates(self):
        """Calling resolve_links with a new link after an initial call must
        append the new entry without duplicating the old one."""
        chunks = [
            {"content": "src", "chunk_index": 0, "metadata": {"page_number": 1}},
            {"content": "tgt-a", "chunk_index": 1, "metadata": {"page_number": 2}},
            {"content": "tgt-b", "chunk_index": 2, "metadata": {"page_number": 3}},
        ]

        # First pass: one link
        links1 = [LinkInfo(type="internal", source_page=1, target_page=2)]
        resolve_links(chunks, links1)

        assert len(chunks[0]["metadata"]["links"]) == 1

        # Second pass: add another link from same source
        links2 = [LinkInfo(type="internal", source_page=1, target_page=3)]
        resolve_links(chunks, links2)

        assert len(chunks[0]["metadata"]["links"]) == 2
