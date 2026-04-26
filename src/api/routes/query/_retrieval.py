"""Retrieval logic for query routes."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select
from ...infrastructure.database.models import Document, Chunk

logger = logging.getLogger(__name__)


async def retrieve_chunks(
    db: "AsyncSession",
    user_id: str,
    document_ids: list[str],
    question: str,
    top_k: int = 5,
) -> list[tuple[Chunk, float]]:
    """Retrieve relevant chunks from documents based on semantic similarity."""
    from ...domain.services.embedding import get_embedder
    
    logger.info(f"Retrieving chunks - user: {user_id}, docs: {document_ids}, question: {question[:50]}...")
    
    try:
        embedder = await get_embedder()
        logger.info("Embedder loaded successfully")
        
        query_embedding = await embedder.embed_text(question)
        logger.info(f"Query embedding generated, dimension: {len(query_embedding)}")
        
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
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
        logger.error(f"Document query failed: {e}")
        return []
    
    if not documents:
        logger.warning("No documents found for user and document_ids")
        return []
    
    try:
        chunk_results = await db.execute(
            select(Chunk).where(Chunk.document_id.in_(document_ids))
        )
        all_chunks = chunk_results.scalars().all()
        logger.info(f"Found {len(all_chunks)} total chunks")
    except Exception as e:
        logger.error(f"Chunk query failed: {e}")
        return []
    
    if not all_chunks:
        logger.warning("No chunks found in documents")
        return []
    
    try:
        chunk_texts = [c.content for c in all_chunks]
        chunk_embeddings = await embedder.embed_texts(chunk_texts)
        logger.info(f"Generated {len(chunk_embeddings)} chunk embeddings")
    except Exception as e:
        logger.error(f"Bulk embedding failed: {e}")
        return []
    
    similarities = []
    for chunk, embedding in zip(all_chunks, chunk_embeddings):
        similarity = sum(q * e for q, e in zip(query_embedding, embedding))
        similarities.append((chunk, similarity))
    
    similarities.sort(key=lambda x: x[1], reverse=True)
    
    top_chunks = similarities[:top_k]
    logger.info(f"Top {len(top_chunks)} chunks with scores: {[(c.id, s) for c, s in top_chunks]}")
    
    return top_chunks