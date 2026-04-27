"""LlamaIndex retrieval service using existing SQLite chunks."""

import logging
import json
from typing import List, Dict, Any
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class LlamaIndexRetrievedChunk:
    """Result from LlamaIndex retrieval."""
    chunk_id: str
    content: str
    score: float
    metadata: Dict[str, Any]
    source: str = "llamaindex"


class SQLiteVectorStoreAdapter:
    """Simple vector store adapter that reads from existing SQLite Chunk table."""
    
    def __init__(self, db_session: AsyncSession, document_ids: List[str]):
        self._db = db_session
        self._document_ids = document_ids
    
    async def get_chunks_with_embeddings(self) -> List[Dict[str, Any]]:
        """Get chunks that have embeddings for specified documents only."""
        from ...infrastructure.database.models import Chunk
        
        # SECURITY FIX: Only fetch chunks for the specified document_ids
        result = await self._db.execute(
            select(Chunk).where(
                Chunk.embedding.isnot(None),
                Chunk.document_id.in_(self._document_ids)  # Filter by document_ids
            )
        )
        chunks = result.scalars().all()
        
        return [
            {
                "id": chunk.id,
                "content": chunk.content,
                "embedding": chunk.embedding if isinstance(chunk.embedding, list) else json.loads(chunk.embedding),
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "metadata": chunk.chunk_metadata or {},
            }
            for chunk in chunks
        ]
    
    async def search(self, query_embedding: List[float], top_k: int = 5) -> List[LlamaIndexRetrievedChunk]:
        """Search by cosine similarity."""
        # SECURITY FIX: Validate top_k parameter
        top_k = max(1, min(top_k, 100))  # Clamp between 1 and 100
        
        chunks = await self.get_chunks_with_embeddings()
        
        if not chunks:
            return []
        
        # Calculate cosine similarity
        similarities = []
        for chunk in chunks:
            emb = chunk["embedding"]
            if emb:
                sim = self._cosine_similarity(query_embedding, emb)
                similarities.append((chunk, sim))
        
        # Sort and get top k
        similarities.sort(key=lambda x: x[1], reverse=True)
        results = []
        
        for chunk, sim in similarities[:top_k]:
            if sim > 0.01:
                results.append(LlamaIndexRetrievedChunk(
                    chunk_id=chunk["id"],
                    content=chunk["content"],
                    score=sim,
                    metadata=chunk["metadata"],
                ))
        
        return results
    
    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class LlamaIndexRetriever:
    """LlamaIndex-based retriever using existing SQLite chunks."""
    
    def __init__(self, db_session: AsyncSession, document_ids: List[str]):
        self._db = db_session
        self._document_ids = document_ids  # Store document_ids
        self._vector_store = SQLiteVectorStoreAdapter(db_session, document_ids)
    
    async def retrieve(
        self,
        question: str,
        top_k: int = 5,
    ) -> List[LlamaIndexRetrievedChunk]:
        """Retrieve relevant chunks using embeddings."""
        from ...domain.services.embedding import get_embedder
        
        # SECURITY FIX: Validate top_k
        top_k = max(1, min(top_k, 100))
        
        embedder = await get_embedder()
        query_embedding = await embedder.embed_text(question)
        
        return await self._vector_store.search(query_embedding, top_k=top_k)


# Global instance management - removed for security
# Each request now creates a fresh instance with document_ids


async def get_llamaindex_retriever(db_session: AsyncSession, document_ids: List[str]) -> LlamaIndexRetriever:
    """Get the LlamaIndex retriever for the specified document_ids."""
    return LlamaIndexRetriever(db_session, document_ids)


def reset_llamaindex_retriever() -> None:
    """No-op - kept for API compatibility."""
    pass