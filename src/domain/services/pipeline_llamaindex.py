"""LlamaIndex pipeline orchestration service."""

import logging
import time
from typing import List, Optional, Dict, Any, AsyncGenerator
from dataclasses import dataclass
from sqlalchemy import select

from ...infrastructure.database.models import Chunk

logger = logging.getLogger(__name__)


@dataclass
class LlamaIndexQueryResult:
    """Result from LlamaIndex query pipeline."""
    answer: str
    sources: List[Dict[str, Any]]
    latency_ms: int
    cached: bool = False


class LlamaIndexPipeline:
    """End-to-end LlamaIndex RAG pipeline."""
    
    def __init__(self, db_session):
        self._db = db_session
    
    async def query(
        self,
        question: str,
        document_ids: List[str],
        top_k: int = 5,
    ) -> LlamaIndexQueryResult:
        """Execute a complete RAG query through LlamaIndex."""
        # SECURITY FIX: Validate top_k
        top_k = max(1, min(top_k, 100))
        
        start_time = time.time()
        
        # Get chunks for the specified documents
        result = await self._db.execute(
            select(Chunk).where(Chunk.document_id.in_(document_ids))
        )
        all_chunks = result.scalars().all()
        
        if not all_chunks:
            return LlamaIndexQueryResult(
                answer="No documents found",
                sources=[],
                latency_ms=int((time.time() - start_time) * 1000),
            )
        
        # Retrieve using our custom retriever
        from .retrieval_llamaindex import LlamaIndexRetriever
        # SECURITY FIX: Pass document_ids to ensure proper access control
        retriever = LlamaIndexRetriever(self._db, document_ids)
        retrieved = await retriever.retrieve(question, top_k=top_k)
        
        if not retrieved:
            return LlamaIndexQueryResult(
                answer="I don't have enough information to answer this question.",
                sources=[],
                latency_ms=int((time.time() - start_time) * 1000),
            )
        
        # Build context from retrieved chunks
        context_text = "\n\n".join([
            f"SOURCE {i+1}: {r.content[:500]}"
            for i, r in enumerate(retrieved[:3])
        ])
        
        # Generate response
        from ...domain.services.llm import get_llm
        llm = await get_llm()
        
        prompt = f"""Answer the question in 2-3 sentences based ONLY on the sources below.
If the information is not in the sources, say: "I don't have enough information."

{context_text}

Question: {question}

Answer:"""
        
        try:
            answer = await llm.generate(prompt)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            answer = "I apologize, but I couldn't generate a proper response."
        
        sources = [
            {
                "chunk_id": r.chunk_id,
                "content": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                "score": r.score,
            }
            for r in retrieved[:5]
        ]
        
        return LlamaIndexQueryResult(
            answer=answer,
            sources=sources,
            latency_ms=int((time.time() - start_time) * 1000),
        )