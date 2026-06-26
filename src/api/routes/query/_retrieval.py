"""Retrieval logic for query routes."""

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import and_, or_, select

from ....core.config import get_settings
from ....core.logging import log_structured
from ....infrastructure.database.models import Chunk, Document

logger = logging.getLogger(__name__)


async def _expand_with_links(
    chunks: list[tuple[Chunk, float]],
    db: "AsyncSession",
    decay_factor: float = 0.85,
    expansion_factor: int = 2,
) -> list[tuple[Chunk, float]]:
    """Expand retrieval results with 1-hop link traversal.

    For each input chunk, reads links/backlinks from chunk_metadata,
    fetches linked chunks from DB, applies score decay, deduplicates,
    and returns the expanded list capped at len(chunks) * expansion_factor.

    .. note::

       Link metadata stores **chunk_index** values (integers), not
       ``Chunk.id`` UUIDs.  We therefore query by ``(document_id,
       chunk_index)`` pairs.
    """
    if not chunks:
        return []

    # Collect referenced chunks.  Link metadata stores **chunk_index**
    # values (integers) — we look those up via ``(document_id,
    # chunk_index)`` pairs.  For backward compatibility with earlier
    # metadata that may contain UUID strings, we also collect those.
    target_refs: set[tuple[str, int]] = set()  # (document_id, chunk_index)
    ids_only: set[str] = set()                 # Chunk.id (UUID fallback)

    for chunk, _score in chunks:
        metadata = chunk.chunk_metadata or {}
        for link in (metadata.get("links") or []):
            for target_id in (link.get("target_chunk_ids") or []):
                if isinstance(target_id, int):
                    target_refs.add((chunk.document_id, target_id))
                elif isinstance(target_id, str) and target_id:
                    ids_only.add(target_id)
        for bl in (metadata.get("backlinks") or []):
            source_id = bl.get("source_chunk_id")
            if isinstance(source_id, int):
                target_refs.add((chunk.document_id, source_id))
            elif isinstance(source_id, str) and source_id:
                ids_only.add(source_id)

    if not target_refs and not ids_only:
        return chunks

    # Fetch referenced chunks
    try:
        conditions: list = [
            and_(Chunk.document_id == doc_id, Chunk.chunk_index == idx)
            for doc_id, idx in target_refs
        ]
        if ids_only:
            conditions.append(Chunk.id.in_(list(ids_only)))
        result = await db.execute(select(Chunk).where(or_(*conditions)))
        # Build lookups
        index_lookup: dict[tuple[str, int], Chunk] = {}  # (doc_id, chunk_index) → Chunk
        id_lookup: dict[str, Chunk] = {}                 # Chunk.id → Chunk
        for c in result.scalars().all():
            index_lookup[(c.document_id, c.chunk_index)] = c
            id_lookup[c.id] = c
    except Exception:
        logger.warning("Failed to fetch linked chunks", exc_info=logger.isEnabledFor(logging.DEBUG))
        return chunks

    # Apply score decay and deduplicate
    linked_chunks: dict[str, tuple[Chunk, float]] = {}  # chunk_id → (chunk, score)

    for chunk, score in chunks:
        metadata = chunk.chunk_metadata or {}

        for link in (metadata.get("links") or []):
            for target_id in (link.get("target_chunk_ids") or []):
                linked: Chunk | None = None
                if isinstance(target_id, int):
                    linked = index_lookup.get((chunk.document_id, target_id))
                elif isinstance(target_id, str):
                    linked = id_lookup.get(target_id)
                if linked is not None:
                    _record_linked(linked_chunks, linked, score, decay_factor)

        for bl in (metadata.get("backlinks") or []):
            source_id = bl.get("source_chunk_id")
            linked = None
            if isinstance(source_id, int):
                linked = index_lookup.get((chunk.document_id, source_id))
            elif isinstance(source_id, str):
                linked = id_lookup.get(source_id)
            if linked is not None:
                _record_linked(linked_chunks, linked, score, decay_factor)

    # Merge original and linked chunks
    result_chunks = list(chunks)
    seen_ids = {c.id for c, _ in chunks}
    for linked_chunk, linked_score in linked_chunks.values():
        if linked_chunk.id not in seen_ids:
            result_chunks.append((linked_chunk, linked_score))

    result_chunks.sort(key=lambda x: x[1], reverse=True)

    max_results = len(chunks) * expansion_factor
    result_chunks = result_chunks[:max_results]

    logger.info(
        "Link traversal expanded %d -> %d chunks (decay=%.2f, factor=%d)",
        len(chunks),
        len(result_chunks),
        decay_factor,
        expansion_factor,
    )
    return result_chunks


def _record_linked(
    linked_chunks: dict[str, tuple[Chunk, float]],
    linked_chunk: Chunk,
    source_score: float,
    decay_factor: float,
) -> None:
    """Record a linked chunk with a decayed score, keeping the higher one."""
    new_score = source_score * decay_factor
    existing = linked_chunks.get(linked_chunk.id)
    if existing is None or new_score > existing[1]:
        linked_chunks[linked_chunk.id] = (linked_chunk, new_score)
    setattr(linked_chunk, "_retrieved_via", "link_traversal")


async def retrieve_chunks(
    db: "AsyncSession",
    user_id: str,
    document_ids: list[str],
    question: str,
    top_k: int = 5,
    link_decay_factor: float = 0.85,
    link_expansion_factor: int = 2,
) -> list[tuple[Chunk, float]]:
    """Retrieve relevant chunks from documents based on semantic similarity."""
    retrieval_start = time.time()
    from ....domain.services.embedding import get_embedder, normalize_embedding, validate_embedding

    try:
        embedder = await get_embedder()

        query_embedding = await embedder.embed_text(question)

        # Normalize query embedding so dot product with normalized stored vectors = cosine similarity
        _retrieval_settings = get_settings()
        if _retrieval_settings.embedding_normalization_enabled:
            query_embedding = normalize_embedding(query_embedding)

    except Exception:
        logger.error("Embedding failed", exc_info=logger.isEnabledFor(logging.DEBUG))
        return []

    try:
        result = await db.execute(
            select(Document).where(
                Document.id.in_(document_ids),
                Document.user_id == user_id,
            )
        )
        documents = result.scalars().all()
    except Exception:
        logger.error("Document query failed", exc_info=logger.isEnabledFor(logging.DEBUG))
        return []

    if not documents:
        logger.warning("No documents found for user and document_ids")
        return []

    try:
        chunk_results = await db.execute(
            select(Chunk).where(
                Chunk.document_id.in_(document_ids),
                Chunk.embedding.isnot(None)
            )
        )
        all_chunks = chunk_results.scalars().all()
    except Exception:
        logger.error("Chunk query failed", exc_info=logger.isEnabledFor(logging.DEBUG))
        return []

    if not all_chunks:
        logger.warning("No chunks found in documents")
        return []

    try:
        chunk_embeddings = [c.embedding for c in all_chunks]
    except Exception:
        logger.error("Failed to load chunk embeddings", exc_info=logger.isEnabledFor(logging.DEBUG))
        return []

    # Validate embeddings before similarity computation using shared utility
    validated_embeddings = []
    invalid_count = 0
    for chunk, emb in zip(all_chunks, chunk_embeddings):
        is_valid, reason = validate_embedding(emb, len(query_embedding), chunk.id)
        if is_valid:
            validated_embeddings.append((chunk, emb))
        else:
            invalid_count += 1
            logger.warning(f"Chunk {chunk.id} has invalid embedding: {reason}")

    similarities: list[tuple[Chunk, float]] = []
    for chunk, embedding in validated_embeddings:
        assert embedding is not None  # validated above
        similarity = sum(q * e for q, e in zip(query_embedding, embedding))
        setattr(chunk, "_retrieved_via", "cosine_similarity")
        similarities.append((chunk, similarity))

    # Min-max normalize scores before applying threshold
    if similarities:
        raw_scores = [s for _, s in similarities]
        from ....domain.services.embedding import normalize_scores
        norm_scores = normalize_scores(raw_scores)
        similarities = [(c, norm_scores[i]) for i, (c, _) in enumerate(similarities)]

    # Filter by minimum relevance score
    _settings = get_settings()
    min_score = _settings.min_relevance_score
    if min_score > 0.0:
        similarities = [(c, s) for c, s in similarities if s >= min_score]
        if not similarities:
            logger.warning(f"No chunks above relevance threshold {min_score}")
            return []

    similarities.sort(key=lambda x: x[1], reverse=True)

    top_chunks = similarities[:top_k]

    # Perform link traversal expansion if there are results
    if top_chunks and (link_decay_factor > 0):
        top_chunks = await _expand_with_links(
            top_chunks, db,
            decay_factor=link_decay_factor,
            expansion_factor=link_expansion_factor,
        )

    log_structured("src.api.routes.query._retrieval", "query",
        user_id=user_id,
        document_count=len(document_ids),
        question_preview=question[:50],
        chunk_count=len(top_chunks),
        top_k=top_k,
        latency_ms=round((time.time() - retrieval_start) * 1000),
    )

    return top_chunks
