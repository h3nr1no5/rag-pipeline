"""Link resolution pass for the link-aware RAG pipeline.

Resolves extracted hyperlinks (LinkInfo objects) to the chunk indices they
originate from and point to, then writes ``links`` and ``backlinks`` arrays
into each chunk's ``chunk_metadata`` dict.

This is a pure synchronous data-transformation step meant to run between
chunking and embedding.
"""

import logging
from typing import Any

from src.infrastructure.parsers.base import LinkInfo

logger = logging.getLogger(__name__)


def _resolve_page_number(chunk: dict[str, Any]) -> int:
    """Extract the page number from a chunk dict, defaulting to 1.

    Checks the following locations (in priority order):
      1. ``metadata["page_number"]``
      2. ``metadata["page"]``
      3. ``metadata["source_page"]``
      4. ``metadata["page_markers"]`` — a list of dicts each containing
         ``"page"``; the first entry's page value is used.
      5. Top-level ``chunk["source_page"]``

    Returns 1 if no page information is found.
    """
    metadata = chunk.get("metadata") or {}

    # Direct page keys in metadata
    for key in ("page_number", "page", "source_page"):
        value = metadata.get(key)
        if isinstance(value, int) and value > 0:
            return value

    # Page markers (list of {page, start_char, end_char})
    page_markers = metadata.get("page_markers")
    if isinstance(page_markers, list) and page_markers:
        first = page_markers[0]
        if isinstance(first, dict):
            page_val = first.get("page")
            if isinstance(page_val, int) and page_val > 0:
                return page_val

    # Top-level source_page fallback
    top_level_page = chunk.get("source_page")
    if isinstance(top_level_page, int) and top_level_page > 0:
        return top_level_page

    return 1


def _get_chunk_id(chunk: dict[str, Any]) -> int:
    """Return a unique identifier for a chunk (its ``chunk_index``)."""
    return chunk.get("chunk_index", 0)


def _ensure_list(metadata: dict[str, Any], key: str) -> list[dict]:
    """Return the list for *key* in *metadata*, creating it if absent."""
    existing = metadata.get(key)
    if existing is None:
        existing = []
        metadata[key] = existing
    return existing


def resolve_links(
    chunks: list[dict[str, Any]],
    all_links: list[LinkInfo],
) -> None:
    """Resolve hyperlinks into per-chunk ``links`` and ``backlinks`` arrays.

    For each chunk dict in *chunks* the function reads its page number from
    ``metadata`` (see :func:`_resolve_page_number`) and builds a
    ``page → [chunk_index, …]`` mapping.  It then processes every
    :class:`LinkInfo` in *all_links*:

    * **Internal links** (``type == "internal"`` with a known ``target_page``)
      — a ``links`` entry is written into the *source* chunk (the chunk on the
      page where the link originates) containing the chunk IDs of every chunk
      on the target page.  A corresponding ``backlinks`` entry is written into
      each *target* chunk.

    * **External links** (``type == "external"``) — a ``links`` entry is
      written into the source chunk with the external URI and an empty target
      chunk list.

    Backlink arrays are capped at **10** entries per chunk.

    **Important:** The function mutates the chunk dicts **in-place** and
    returns ``None``.  It is safe to call multiple times — new entries are
    appended to any existing ``links`` / ``backlinks`` arrays rather than
    overwriting them.

    Parameters
    ----------
    chunks:
        List of chunk dicts, each expected to have at least ``"content"``,
        ``"chunk_index"``, and ``"metadata"`` keys.
    all_links:
        Hyperlinks extracted from the document (e.g. via
        :meth:`DocumentParser.extract_links`).

    Raises
    ------
    TypeError
        If *chunks* or *all_links* is ``None``.
    """
    if chunks is None:
        raise TypeError("chunks must not be None")
    if all_links is None:
        raise TypeError("all_links must not be None")

    if not chunks or not all_links:
        logger.debug("No chunks or no links to resolve; skipping.")
        return

    # ------------------------------------------------------------------
    # 1. Build page → [chunk_index, …] map
    # ------------------------------------------------------------------
    page_to_chunks: dict[int, list[int]] = {}
    for chunk in chunks:
        page = _resolve_page_number(chunk)
        cid = _get_chunk_id(chunk)
        page_to_chunks.setdefault(page, []).append(cid)

    # Build a reverse lookup: chunk_index → chunk dict (for quick access)
    chunk_by_index: dict[int, dict[str, Any]] = {
        _get_chunk_id(c): c for c in chunks
    }

    logger.debug(
        "Link resolution: %d pages mapped from %d chunks, %d links to process",
        len(page_to_chunks),
        len(chunks),
        len(all_links),
    )

    # ------------------------------------------------------------------
    # 2. Process each link
    # ------------------------------------------------------------------
    for link in all_links:
        source_page = link.source_page or 1

        # Source chunk(s) on the link's origin page
        source_chunk_ids = page_to_chunks.get(source_page, [])
        if not source_chunk_ids:
            logger.debug(
                "No chunks found for source page %d; skipping link %s",
                source_page,
                link,
            )
            continue

        if link.type == "internal" and link.target_page is not None:
            _process_internal_link(
                link=link,
                source_chunk_ids=source_chunk_ids,
                target_chunk_ids=page_to_chunks.get(link.target_page, []),
                chunk_by_index=chunk_by_index,
            )
        elif link.type == "external":
            _process_external_link(
                link=link,
                source_chunk_ids=source_chunk_ids,
                chunk_by_index=chunk_by_index,
            )


def _process_internal_link(
    link: LinkInfo,
    source_chunk_ids: list[int],
    target_chunk_ids: list[int],
    chunk_by_index: dict[int, dict[str, Any]],
) -> None:
    """Write forward links and backlinks for an internal link.

    *Forward* (``links``): added to every chunk that shares the link's source
    page.  *Backward* (``backlinks``): added to every chunk that lies on the
    link's target page.
    """
    if not target_chunk_ids:
        logger.debug(
            "No target chunks for internal link to page %d; skipping.",
            link.target_page,
        )
        return

    link_entry: dict[str, Any] = {
        "type": "internal",
        "target_chunk_ids": list(target_chunk_ids),
        "target_page": link.target_page,
        "uri": None,
    }

    # Write forward links into every chunk on the source page.
    for cid in source_chunk_ids:
        chunk = chunk_by_index.get(cid)
        if chunk is None:
            continue
        metadata = chunk.setdefault("metadata", {})
        links_list = _ensure_list(metadata, "links")
        # Avoid duplicating an identical link entry.
        if link_entry not in links_list:
            links_list.append(link_entry)

    # Write backlinks into every target chunk.
    for cid in target_chunk_ids:
        chunk = chunk_by_index.get(cid)
        if chunk is None:
            continue
        metadata = chunk.setdefault("metadata", {})
        backlinks_list = _ensure_list(metadata, "backlinks")

        # For each source chunk on the origin page, add one backlink entry
        # (instead of a single entry with ``source_chunk_id: None``).
        for src_cid in source_chunk_ids:
            src_chunk = chunk_by_index.get(src_cid)
            if src_chunk is None:
                continue
            entry = {
                "source_chunk_id": src_cid,
                "anchor_text": link.anchor_text,
            }
            if entry not in backlinks_list:
                backlinks_list.append(entry)

        # Cap backlinks at 10 entries per chunk.
        if len(backlinks_list) > 10:
            backlinks_list[:] = backlinks_list[:10]


def _process_external_link(
    link: LinkInfo,
    source_chunk_ids: list[int],
    chunk_by_index: dict[int, dict[str, Any]],
) -> None:
    """Write a forward link entry for an external URI."""
    link_entry: dict[str, Any] = {
        "type": "external",
        "uri": link.uri,
        "target_chunk_ids": [],
        "target_page": None,
    }

    for cid in source_chunk_ids:
        chunk = chunk_by_index.get(cid)
        if chunk is None:
            continue
        metadata = chunk.setdefault("metadata", {})
        links_list = _ensure_list(metadata, "links")
        if link_entry not in links_list:
            links_list.append(link_entry)
