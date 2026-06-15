"""LlamaIndex retrieval service using SQLite-backed nodes with hybrid retrieval.

Replaces the old Chroma-backed VectorStoreIndex with direct SQLite-based
chunk loading. Retrieval uses embedding similarity + BM25 keyword search
with RRF fusion, cross-encoder reranking, and direct LLM response synthesis.
"""

import logging
from dataclasses import dataclass
from typing import Any

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, TextNode
from sqlalchemy import select

from ...core.config import get_settings
from ...infrastructure.database.models import Chunk
from .embedding import get_embedder, normalize_embedding

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

    Uses SQLite-stored node embeddings for dense retrieval and a BM25 index
    built from the same node corpus for sparse retrieval.
    """

    def __init__(
        self,
        nodes: list[NodeWithScore],
        embeddings: list[list[float] | None],
        similarity_top_k: int = 20,
        bm25_top_k: int = 20,
        final_top_k: int = 10,
    ) -> None:
        super().__init__()
        self._nodes = nodes
        self._embeddings = embeddings
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

    async def _dense_retrieve(self, query: str) -> list[NodeWithScore]:
        """Perform dense retrieval using dot-product similarity against stored embeddings."""
        embedder = await get_embedder()
        query_emb = await embedder.embed_text(query)
        if settings.embedding_normalization_enabled:
            query_emb = normalize_embedding(query_emb)

        scores = []
        for node_emb in self._embeddings:
            if node_emb is None:
                scores.append(0.0)
            else:
                score = sum(q * e for q, e in zip(query_emb, node_emb))
                scores.append(score)

        top_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )[:self._similarity_top_k]

        dense_nodes = []
        for idx in top_indices:
            node = self._nodes[idx]
            node.score = scores[idx]
            dense_nodes.append(node)

        return dense_nodes

    async def _aretrieve(self, query_bundle: Any) -> list[NodeWithScore]:
        # Extract query string from QueryBundle (passed by RetrieverQueryEngine)
        query = query_bundle.query_str if hasattr(query_bundle, "query_str") else str(query_bundle)

        # Dense retrieval via SQLite-stored embeddings
        dense_nodes = await self._dense_retrieve(query)

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

    def __init__(self, db, document_ids: list[str]) -> None:
        self._db = db
        self._document_ids = document_ids
        self._retriever: HybridRetriever | None = None
        self._reranker: Any = None

    async def _ensure_components(self):
        """Lazy-load retriever and reranker from SQLite chunks."""
        if self._retriever is not None:
            return

        # Query SQLite directly for chunks matching the document_ids
        result = await self._db.execute(
            select(Chunk)
            .where(Chunk.document_id.in_(self._document_ids))
            .order_by(Chunk.chunk_index)
        )
        all_chunks = result.scalars().all()

        if not all_chunks:
            logger.warning(f"No chunks found for document_ids {self._document_ids}")
            raise ValueError(f"No chunks found for document_ids {self._document_ids}")

        # Build NodeWithScore objects and parallel embeddings list
        nodes = []
        embeddings: list[list[float] | None] = []
        for chunk in all_chunks:
            metadata: dict[str, Any] = {
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "chunk_id": chunk.id,
            }
            if chunk.chunk_metadata:
                metadata.update(chunk.chunk_metadata)

            text_node = TextNode(
                id_=chunk.id,
                text=chunk.content,
                metadata=metadata,
            )
            node = NodeWithScore(node=text_node, score=0.0)
            nodes.append(node)
            embeddings.append(chunk.embedding)

        logger.info(
            "Loaded %d chunks from SQLite for document_ids %s",
            len(nodes), self._document_ids,
        )

        self._retriever = HybridRetriever(
            nodes=nodes,
            embeddings=embeddings,
            similarity_top_k=20,
            bm25_top_k=20,
            final_top_k=10,
        )

        # Cross-encoder reranker (lazy, may be unavailable)
        from .retrieval_langchain import CrossEncoderReRanker

        class _ResilientReranker:
            """Wraps CrossEncoderReRanker with graceful fallback."""

            def __init__(self) -> None:
                self._reranker = CrossEncoderReRanker()

            async def rerank(
                self, nodes: list[NodeWithScore], query: str
            ) -> list[NodeWithScore]:
                if not nodes:
                    return nodes
                try:
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
                except Exception as e:
                    logger.warning(f"Cross-encoder reranking skipped (unavailable): {e}")
                return nodes

        self._reranker = _ResilientReranker()

    async def _build_context(self, nodes: list[NodeWithScore]) -> str:
        """Build context string from retrieved nodes with source citations."""
        parts = []
        for i, node in enumerate(nodes, 1):
            parts.append(f"Source {i}:\n{node.text}")
        return "\n\n".join(parts)

    async def _retrieve_and_rerank(
        self, question: str, top_k: int
    ) -> list[NodeWithScore]:
        """Retrieve nodes via hybrid search + reranking."""
        await self._ensure_components()
        self._retriever._final_top_k = top_k

        # Retrieve via the public aretrieve method (handles QueryBundle coercion)
        nodes = await self._retriever.aretrieve(question)

        # Apply cross-encoder reranker
        nodes = await self._reranker.rerank(nodes, question)

        # Min-max normalize scores
        if nodes:
            scores = [n.score or 0.0 for n in nodes]
            min_s = min(scores)
            max_s = max(scores)
            if max_s - min_s > 1e-10:
                for n in nodes:
                    n.score = (n.score - min_s) / (max_s - min_s)

        return nodes

    def _nodes_to_chunks(
        self, nodes: list[NodeWithScore]
    ) -> list[LlamaIndexRetrievedChunk]:
        """Convert NodeWithScore list to LlamaIndexRetrievedChunk list."""
        results = []
        for node in nodes:
            chunk_id = node.metadata.get("chunk_id", node.node_id)
            results.append(LlamaIndexRetrievedChunk(
                chunk_id=chunk_id,
                content=node.text,
                score=node.score or 0.0,
                metadata=dict(node.metadata),
            ))
        return results

    async def retrieve(
        self,
        question: str,
        top_k: int = 5,
    ) -> list[LlamaIndexRetrievedChunk]:
        """Retrieve relevant chunks using hybrid retrieval + cross-encoder reranking."""
        nodes = await self._retrieve_and_rerank(question, top_k)

        # Filter by min_relevance_score
        filtered = [n for n in nodes if (n.score or 0.0) >= settings.min_relevance_score]

        return self._nodes_to_chunks(filtered[:top_k])

    async def generate(
        self,
        question: str,
        top_k: int = 5,
        max_tokens: int = 600,
        temperature: float = 0.5,
    ) -> tuple[str, list[LlamaIndexRetrievedChunk]]:
        """Generate a response using hybrid retrieval + direct LLM synthesis."""
        nodes = await self._retrieve_and_rerank(question, top_k)

        # Build context
        context = await self._build_context(nodes[:top_k])

        # Format prompt
        prompt = (
            "You are a helpful assistant. Answer questions based ONLY on the provided sources below.\n"
            "If the answer cannot be determined from the sources, say "
            "\"I don't have enough information to answer this question.\"\n\n"
            "For EVERY factual statement you make, include a source citation in brackets "
            "like [Source 1] immediately after the statement.\n\n"
            "IMPORTANT: Avoid repeating information. Present information in plain text "
            "without Markdown formatting (no headings, no bold, no italics).\n\n"
            "---------------------\n"
            f"{context}\n"
            "---------------------\n"
            f"Question: {question}\n"
            "Answer: "
        )

        # Generate response using the project's MLX LLM
        from .mlx_llama_integration import MLXLlamaIndexLLM

        llm = MLXLlamaIndexLLM()
        response = await llm.acomplete(prompt, max_tokens=max_tokens, temperature=temperature)

        return response.text, self._nodes_to_chunks(nodes[:top_k])

    async def generate_stream(
        self,
        question: str,
        top_k: int = 5,
        max_tokens: int = 600,
        temperature: float = 0.5,
    ):
        """Stream a response using hybrid retrieval + direct LLM streaming."""
        nodes = await self._retrieve_and_rerank(question, top_k)

        # Build context
        context = await self._build_context(nodes[:top_k])

        # Format prompt
        prompt = (
            "You are a helpful assistant. Answer questions based ONLY on the provided sources below.\n"
            "If the answer cannot be determined from the sources, say "
            "\"I don't have enough information to answer this question.\"\n\n"
            "For EVERY factual statement you make, include a source citation in brackets "
            "like [Source 1] immediately after the statement.\n\n"
            "IMPORTANT: Avoid repeating information. Present information in plain text "
            "without Markdown formatting (no headings, no bold, no italics).\n\n"
            "---------------------\n"
            f"{context}\n"
            "---------------------\n"
            f"Question: {question}\n"
            "Answer: "
        )

        # Generate response using the project's MLX LLM
        from .mlx_llama_integration import MLXLlamaIndexLLM

        llm = MLXLlamaIndexLLM()

        collected: list[str] = []
        async for token in llm.astream_complete(
            prompt, max_tokens=max_tokens, temperature=temperature
        ):
            collected.append(token.text)
            yield token.text, self._nodes_to_chunks(nodes[:top_k])

        # Final yield with full answer and sources
        full_answer = "".join(collected)
        yield full_answer, self._nodes_to_chunks(nodes[:top_k])


class _NodeWrapper:
    """Minimal wrapper to adapt NodeWithScore for CrossEncoderReRanker API."""

    def __init__(self, node: NodeWithScore) -> None:
        self.content = node.text
        self.chunk_id = node.node_id
        self.score = node.score or 0.0
        self.metadata = dict(node.metadata)


async def get_llamaindex_retriever(db, document_ids: list[str]) -> LlamaIndexRetriever:
    """Get a LlamaIndex retriever instance for the given document_ids."""
    return LlamaIndexRetriever(db, document_ids)
