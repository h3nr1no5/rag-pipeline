"""LlamaIndex pipeline orchestration service."""

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from ...infrastructure.database.models import Chunk

logger = logging.getLogger(__name__)


@dataclass
class LlamaIndexQueryResult:
    """Result from LlamaIndex query pipeline."""
    answer: str
    sources: list[dict[str, Any]]
    latency_ms: int
    cached: bool = False


class LlamaIndexPipeline:
    """End-to-end LlamaIndex RAG pipeline."""

    def __init__(self, db_session):
        self._db = db_session

    async def query(
        self,
        question: str,
        document_ids: list[str],
        top_k: int = 5,
        response_length: str = "normal",
        include_citations: bool = True,
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

        # Generate response using shared prompt builder (includes anti-repetition, citations, length control)
        from ...domain.services.llm import get_llm
        from .prompt_builder import build_prompt
        llm = await get_llm()

        prompt = build_prompt(question, retrieved, prompt_sources=3,
                              include_citations=include_citations,
                              response_length=response_length)

        try:
            answer = await llm.generate(prompt)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            answer = "I apologize, but I couldn't generate a proper response."

        sources = [
            {
                "chunk_id": r.chunk_id,
                "content": r.content,
                "score": r.score,
            }
            for r in retrieved[:5]
        ]

        return LlamaIndexQueryResult(
            answer=answer,
            sources=sources,
            latency_ms=int((time.time() - start_time) * 1000),
        )
