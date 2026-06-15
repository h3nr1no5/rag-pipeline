"""LlamaIndex retrieval service using Chroma-backed VectorStoreIndex.

Replaces the old custom SQLite adapter with a proper LlamaIndex integration
that uses Chroma for vector storage, hybrid retrieval (embedding + BM25),
cross-encoder reranking, and LlamaIndex-native response synthesis.
"""

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from llama_index.core import VectorStoreIndex, get_response_synthesizer
from llama_index.core.schema import NodeWithScore
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.prompts import PromptTemplate
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.node_parser import SentenceSplitter

from ...core.config import get_settings
from .llama_index_service import get_llama_index_service

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class LlamaIndexRetrievedChunk:
    """Result from LlamaIndex retrieval."""
    chunk_id: str
    content: str
    score: float
    metadata: dict[str, Any]
    source: str = "llamaindex"


class HybridRetriever(BaseRetriever):
    """Hybrid retriever: embedding similarity + BM25 keyword search fused via RRF.

    Uses the Chroma vector store for dense retrieval and a BM25 index
    built from the same node corpus for sparse retrieval.
    """

    def __init__(
        self,
        vector_index: VectorStoreIndex,
        nodes: list[NodeWithScore],
        similarity_top_k: int = 20,
        bm25_top_k: int = 20,
        final_top_k: int = 10,
    ) -> None:
        super().__init__()
        self._vector_index = vector_index
        self._nodes = nodes
        self._similarity_top_k = similarity_top_k
        self._bm25_top_k = bm25_top_k
        self._final_top_k = final_top_k
        self._bm25 = self._build_bm25(nodes)

    @staticmethod
    def _build_bm25(nodes: list[NodeWithScore]):
        """Build a BM25 index from the node corpus."""
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank-bm25 not available; BM25 retrieval disabled")
            return None
        corpus = [node.text for node in nodes]
        tokenized = [doc.split() for doc in corpus]
        logger.info(f"Built BM25 index from {len(corpus)} nodes")
        return BM25Okapi(tokenized)

    def _retrieve(self, query: str) -> list[NodeWithScore]:
        """Sync retrieval (not used -- use _aretrieve)."""
        raise NotImplementedError("Use async methods")

    async def _aretrieve(self, query: str) -> list[NodeWithScore]:
        # Dense retrieval
        vector_retriever = self._vector_index.as_retriever(
            similarity_top_k=self._similarity_top_k
        )
        dense_nodes = await vector_retriever.aretrieve(query)

        # Sparse retrieval via BM25
        bm25_nodes: list[NodeWithScore] = []
        if self._bm25 is not None:
            tokenized_query = query.split()
            bm25_scores = self._bm25.get_scores(tokenized_query)
            top_indices = sorted(
                range(len(bm25_scores)),
                key=lambda i: bm25_scores[i],
                reverse=True,
            )[:self._bm25_top_k]

            for idx in top_indices:
                if bm25_scores[idx] > 0:
                    node = self._nodes[idx]
                    node.score = float(bm25_scores[idx])
                    bm25_nodes.append(node)

        # Reciprocal Rank Fusion (RRF)
        seen_ids: dict[str, float] = {}
        for rank, node in enumerate(dense_nodes):
            node_id = node.node_id
            seen_ids[node_id] = seen_ids.get(node_id, 0.0) + 1.0 / (rank + 60)

        for rank, node in enumerate(bm25_nodes):
            node_id = node.node_id
            seen_ids[node_id] = seen_ids.get(node_id, 0.0) + 1.0 / (rank + 60)

        merged = sorted(seen_ids.items(), key=lambda x: x[1], reverse=True)
        top_ids = set(pid for pid, _ in merged[:self._final_top_k])

        result = []
        for node in dense_nodes + bm25_nodes:
            if node.node_id in top_ids and node not in result:
                rrf_score = seen_ids.get(node.node_id, 0.0)
                node.score = rrf_score
                result.append(node)
            if len(result) >= self._final_top_k:
                break

        return result


class LlamaIndexRetriever:
    """High-level LlamaIndex retriever with hybrid search, reranking, and synthesis."""

    def __init__(self, document_ids: list[str]) -> None:
        self._document_ids = document_ids
        self._service: Optional[Any] = None
        self._index: Optional[VectorStoreIndex] = None
        self._query_engine: Optional[RetrieverQueryEngine] = None

    async def _ensure_engine(self) -> RetrieverQueryEngine:
        if self._query_engine is not None:
            return self._query_engine

        self._service = await get_llama_index_service()
        self._index = await self._service.get_index()

        # Build node list from index (needed for BM25)
        retriever = self._index.as_retriever(similarity_top_k=50)
        all_nodes = await retriever.aretrieve("")

        # Security: filter nodes to only those belonging to the requested documents
        doc_id_set = set(self._document_ids)
        filtered_nodes = [
            n for n in all_nodes
            if n.metadata.get("document_id") in doc_id_set
        ]
        logger.info(
            "Filtered %d nodes to %d for document_ids %s",
            len(all_nodes), len(filtered_nodes), self._document_ids
        )

        hybrid_retriever = HybridRetriever(
            vector_index=self._index,
            nodes=filtered_nodes,
            similarity_top_k=20,
            bm25_top_k=20,
            final_top_k=10,
        )

        # Cross-encoder reranker
        from .retrieval_langchain import CrossEncoderReRanker

        class CrossEncoderNodeReranker:
            """Wraps CrossEncoderReRanker as a LlamaIndex node post-processor."""

            def __init__(self) -> None:
                self._reranker = CrossEncoderReRanker()

            async def postprocess_nodes(
                self, nodes: list[NodeWithScore], query: str
            ) -> list[NodeWithScore]:
                if not nodes:
                    return nodes
                scored = await self._reranker.rerank(
                    query,
                    [_NodeWrapper(n) for n in nodes],
                    top_k=len(nodes),
                )
                score_map = {s.chunk_id: s.score for s in scored}
                for node in nodes:
                    if node.node_id in score_map:
                        node.score = score_map[node.node_id]
                nodes.sort(key=lambda n: n.score or 0.0, reverse=True)
                return nodes

        reranker = CrossEncoderNodeReranker()

        # Custom prompt for response synthesis
        prompt_template = PromptTemplate(
            "You are a helpful assistant. Answer questions based ONLY on the provided sources below.\n"
            "If the answer cannot be determined from the sources, say "
            "\"I don't have enough information to answer this question.\"\n\n"
            "For EVERY factual statement you make, include a source citation in brackets "
            "like [Source 1] immediately after the statement.\n\n"
            "IMPORTANT: Avoid repeating information. Present information in plain text "
            "without Markdown formatting (no headings, no bold, no italics).\n\n"
            "---------------------\n"
            "{context_str}\n"
            "---------------------\n"
            "Question: {query_str}\n"
            "Answer: "
        )

        # Response synthesizer
        from .mlx_llama_integration import MLXLlamaIndexLLM
        llm = MLXLlamaIndexLLM()

        synth = get_response_synthesizer(
            llm=llm,
            text_qa_template=prompt_template,
            refine_template=prompt_template,
            response_mode="compact",
            use_async=True,
        )

        # Build query engine
        self._query_engine = RetrieverQueryEngine(
            retriever=hybrid_retriever,
            response_synthesizer=synth,
            node_postprocessors=[reranker],
        )
        return self._query_engine

    async def retrieve(
        self,
        question: str,
        top_k: int = 5,
    ) -> list[LlamaIndexRetrievedChunk]:
        """Retrieve relevant chunks using hybrid retrieval + cross-encoder reranking."""
        engine = await self._ensure_engine()

        # Override retriever top_k
        engine._retriever._final_top_k = top_k

        # Use retriever directly (skip synthesis for chunk retrieval)
        nodes = await engine._retriever.aretrieve(question)

        # Apply cross-encoder reranker
        for processor in engine._node_postprocessors:
            nodes = await processor.postprocess_nodes(nodes, question)

        # Min-max normalize scores
        if nodes:
            scores = [n.score or 0.0 for n in nodes]
            min_s = min(scores)
            max_s = max(scores)
            if max_s - min_s > 1e-10:
                for n in nodes:
                    n.score = (n.score - min_s) / (max_s - min_s)

        # Filter by min_relevance_score
        filtered = [n for n in nodes if (n.score or 0.0) >= settings.min_relevance_score]

        results = []
        for node in filtered[:top_k]:
            chunk_id = node.metadata.get("chunk_id", node.node_id)
            results.append(LlamaIndexRetrievedChunk(
                chunk_id=chunk_id,
                content=node.text,
                score=node.score or 0.0,
                metadata=dict(node.metadata),
            ))
        return results

    async def generate(
        self,
        question: str,
        top_k: int = 5,
        max_tokens: int = 600,
        temperature: float = 0.5,
    ) -> tuple[str, list[LlamaIndexRetrievedChunk]]:
        """Generate a response using the full LlamaIndex query engine."""
        engine = await self._ensure_engine()
        engine._retriever._final_top_k = top_k

        response = await engine.aquery(question)
        answer = str(response)

        sources = []
        for node in response.source_nodes:
            chunk_id = node.metadata.get("chunk_id", node.node_id)
            sources.append(LlamaIndexRetrievedChunk(
                chunk_id=chunk_id,
                content=node.text,
                score=node.score or 0.0,
                metadata=dict(node.metadata),
            ))

        return answer, sources

    async def generate_stream(
        self,
        question: str,
        top_k: int = 5,
        max_tokens: int = 600,
        temperature: float = 0.5,
    ):
        """Stream a response using the full LlamaIndex query engine."""
        engine = await self._ensure_engine()
        engine._retriever._final_top_k = top_k

        response = await engine.aquery(question)
        answer = str(response)

        sources = []
        for node in response.source_nodes:
            chunk_id = node.metadata.get("chunk_id", node.node_id)
            sources.append(LlamaIndexRetrievedChunk(
                chunk_id=chunk_id,
                content=node.text,
                score=node.score or 0.0,
                metadata=dict(node.metadata),
            ))

        yield answer, sources


class _NodeWrapper:
    """Minimal wrapper to adapt NodeWithScore for CrossEncoderReRanker API."""

    def __init__(self, node: NodeWithScore) -> None:
        self.content = node.text
        self.chunk_id = node.node_id
        self.score = node.score or 0.0
        self.metadata = dict(node.metadata)


async def get_llamaindex_retriever(document_ids: list[str]) -> LlamaIndexRetriever:
    """Get a LlamaIndex retriever instance for the given document_ids."""
    return LlamaIndexRetriever(document_ids)


def reset_llamaindex_retriever() -> None:
    """Reset the retriever state."""
    from .llama_index_service import reset_llama_index_service
    reset_llama_index_service()
