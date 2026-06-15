"""Retrieval logic for query routes."""

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import and_, or_, select
from ....core.config import get_settings
from ....infrastructure.database.models import Document, Chunk

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
    except Exception as e:
        logger.warning("Failed to fetch linked chunks", exc_info=logger.isEnabledFor(logging.DEBUG))
        return chunks

    # Apply score decay and deduplicate
    linked_chunks: dict[str, tuple[Chunk, float]] = {}  # chunk_id → (chunk, score)

    for chunk, score in chunks:
        metadata = chunk.chunk_metadata or {}

        for link in (metadata.get("links") or []):
            for target_id in (link.get("target_chunk_ids") or []):
                linked: Optional[Chunk] = None
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
    from ....domain.services.embedding import get_embedder
    
    logger.info(f"Retrieving chunks - user: {user_id}, docs: {document_ids}, question: {question[:50]}...")
    
    try:
        embedder = await get_embedder()
        logger.info("Embedder loaded successfully")
        
        query_embedding = await embedder.embed_text(question)
        logger.info(f"Query embedding generated, dimension: {len(query_embedding)}")
        
    except Exception as e:
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
        logger.info(f"Found {len(documents)} documents for user")
    except Exception as e:
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
        logger.info(f"Found {len(all_chunks)} total chunks")
    except Exception as e:
        logger.error("Chunk query failed", exc_info=logger.isEnabledFor(logging.DEBUG))
        return []
    
    if not all_chunks:
        logger.warning("No chunks found in documents")
        return []
    
    try:
        chunk_embeddings = [c.embedding for c in all_chunks]
        logger.info(f"Loaded {len(chunk_embeddings)} stored chunk embeddings")
    except Exception as e:
        logger.error("Failed to load chunk embeddings", exc_info=logger.isEnabledFor(logging.DEBUG))
        return []
    
    # Validate embeddings before similarity computation
    validated_embeddings = []
    for chunk, emb in zip(all_chunks, chunk_embeddings):
        if emb is None:
            continue  # safety skip
        if not isinstance(emb, (list, tuple)):
            logger.warning(f"Chunk {chunk.id} has non-list embedding type {type(emb).__name__}, skipping")
            continue
        if len(emb) != len(query_embedding):
            logger.warning(
                f"Chunk {chunk.id} embedding dimension {len(emb)} "
                f"does not match query dimension {len(query_embedding)}, skipping"
            )
            continue
        # Reject NaN / inf values
        if any(not isinstance(v, (int, float)) or (v != v) for v in emb):  # NaN check via v != v
            logger.warning(f"Chunk {chunk.id} contains NaN or non-numeric values in embedding, skipping")
            continue
        if any(abs(v) == float('inf') for v in emb):
            logger.warning(f"Chunk {chunk.id} contains infinite values in embedding, skipping")
            continue
        validated_embeddings.append((chunk, emb))
    
    logger.info(f"Validated {len(validated_embeddings)}/{len(all_chunks)} chunk embeddings")
    
    similarities = []
    for chunk, embedding in validated_embeddings:
        similarity = sum(q * e for q, e in zip(query_embedding, embedding))
        setattr(chunk, "_retrieved_via", "cosine_similarity")
        similarities.append((chunk, similarity))
    
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
    logger.info(f"Top {len(top_chunks)} chunks with scores: {[(c.id, s) for c, s in top_chunks]}")
    
    # Perform link traversal expansion if there are results
    if top_chunks and (link_decay_factor > 0):
        top_chunks = await _expand_with_links(
            top_chunks, db,
            decay_factor=link_decay_factor,
            expansion_factor=link_expansion_factor,
        )
    
    return top_chunks