"""Hybrid retriever orchestrating BM25, embedding, RRF, link traversal,
and parent expansion for API documentation.

Task 5.6: HybridRetriever implementation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.domain.rag.api_docs.retrieval.link_traverser import LinkTraverser
from src.domain.rag.api_docs.retrieval.parent_expander import ParentExpander
from src.domain.rag.api_docs.retrieval.rrf import RrfFusion
from src.domain.services.embedding import normalize_scores

if TYPE_CHECKING:
    from src.domain.rag.api_docs.chunking.builder import ChunkGraph
    from src.domain.rag.api_docs.chunking.graph import ChunkNode
    from src.domain.rag.api_docs.chunking.text_formatter import ChunkTextFormatter
    from src.domain.rag.api_docs.model.models import (
        APIEnum,
        APIErrorCode,
        APIInterface,
    )
    from src.domain.rag.api_docs.retrieval.bm25_index import ApiBm25Index
    from src.domain.rag.api_docs.retrieval.embedding_index import ApiEmbeddingIndex

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Orchestrator for hybrid API doc retrieval.

    The retrieval pipeline is::

        BM25 search  ─┐
                       ├── RRF fusion → top_k → link traversal
        Embedding search ─┘                    → parent expansion
                                               → deduplication
                                               → (ChunkNode, score) tuples
    """

    def __init__(
        self,
        bm25_index: ApiBm25Index,
        embedding_index: ApiEmbeddingIndex,
        graph: ChunkGraph,
        rerank_k: int = 20,
    ) -> None:
        self.bm25_index = bm25_index
        self.embedding_index = embedding_index
        self.graph = graph
        self._rrf = RrfFusion(k=60)
        self._link_traverser = LinkTraverser()
        self._parent_expander = ParentExpander()
        if not isinstance(rerank_k, int) or rerank_k < 0:
            raise ValueError(f"rerank_k must be a non-negative integer, got {rerank_k!r}")
        self._rerank_k = rerank_k  # Number of RRF-fused candidates to rerank with cross-encoder
        self._reranker: object | None = None  # Lazy-loaded CrossEncoderReRanker singleton

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def retrieve(
        self, query: str, top_k: int = 10, rerank_k: int | None = None
    ) -> list[tuple[ChunkNode, float]]:
        """Run the full hybrid retrieval pipeline.

        Args:
            query: Free-text or keyword query.
            top_k: Target number of results (used as a target — the final
                   list may be larger after link traversal / parent expansion).
            rerank_k: Number of RRF-fused candidates to rerank with cross-encoder.
                      Overrides ``self._rerank_k`` when provided.  Set to 0 to
                      skip reranking.

        Returns:
            List of ``(ChunkNode, score)`` tuples sorted by descending score.
            After reranking, scores are cross-encoder scores normalized to [0, 1].
            Chunks not found in the graph are silently skipped.
        """
        # 1 & 2: Search both indexes (double top_k for intermediate fusion)
        bm25_results = self.bm25_index.search(query, top_k=top_k * 2)
        embedding_results = await self.embedding_index.search(query, top_k=top_k * 2)

        # 3: Fuse with RRF
        fused = self._rrf.fuse([bm25_results, embedding_results])

        # 4: Cross-encoder reranking (after RRF fusion, before link traversal)
        actual_rerank_k = rerank_k if rerank_k is not None else self._rerank_k
        did_rerank = actual_rerank_k > 0 and bool(fused)
        if did_rerank:
            # Separate into candidates (to be reranked) and remaining (keep RRF scores)
            rerank_candidates = fused[:actual_rerank_k]
            remaining = fused[actual_rerank_k:]

            # Rerank candidates with cross-encoder
            reranked = await self._rerank_results(query, rerank_candidates)

            # Log original RRF scores for debugging
            rrf_scores = {cid: s for cid, s in fused}
            logger.debug(
                "Reranked %d/%d fused candidates — RRF scores range: "
                "[%.4f..%.4f]",
                len(reranked),
                len(fused),
                min(rrf_scores.values()),
                max(rrf_scores.values()),
            )
            # Normalize only cross-encoder scores to [0, 1]
            if reranked:
                ce_scores = [s for _, s in reranked]
                normalized = normalize_scores(ce_scores)
                reranked = [(cid, ns) for (cid, _), ns in zip(reranked, normalized)]

            # Re-combine: cross-encoder-scored items first, then remaining
            reranked_ids = {cid for cid, _ in reranked}
            rest = [(cid, s) for cid, s in remaining if cid not in reranked_ids]
            reranked = reranked + rest
        else:
            if actual_rerank_k == 0:
                logger.debug("Reranking skipped (rerank_k=0)")
            reranked = fused

        # 5: Take the requested top_k from reranked results
        top_chunk_ids = [doc_id for doc_id, _ in reranked[:top_k]]

        # 6: Link traversal
        expanded_ids = self._link_traverser.traverse(top_chunk_ids, self.graph)

        # 7: Parent expansion
        final_ids = self._parent_expander.expand(expanded_ids, self.graph)

        # 8: Deduplicate while preserving order
        seen: set[str] = set()
        ordered_ids: list[str] = []
        for cid in final_ids:
            if cid not in seen:
                seen.add(cid)
                ordered_ids.append(cid)

        # 9: Build (ChunkNode, score) tuples
        score_map = dict(reranked) if did_rerank else dict(fused)
        results: list[tuple[ChunkNode, float]] = []
        for cid in ordered_ids:
            node = self.graph.nodes.get(cid)
            if node is not None:
                score = score_map.get(cid, 0.0)
                results.append((node, score))

        logger.info(
            "HybridRetrieve: query=%r top_k=%d rerank_k=%d → %d bm25 / %d embed "
            "→ fused=%d → expanded=%d final=%d",
            query,
            top_k,
            actual_rerank_k,
            len(bm25_results),
            len(embedding_results),
            len(fused),
            len(expanded_ids),
            len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Cross-encoder reranking helpers
    # ------------------------------------------------------------------

    async def _get_reranker(self) -> object:
        """Lazy-load the shared CrossEncoderReRanker singleton."""
        if self._reranker is None:
            from src.domain.services.retrieval_langchain import CrossEncoderReRanker

            self._reranker = CrossEncoderReRanker()
        return self._reranker

    async def _rerank_results(
        self,
        query: str,
        candidates: list[tuple[str, float]],
    ) -> list[tuple[str, float]]:
        """Rerank candidate chunks using the cross-encoder.

        Only chunks with non-empty content are scored.  Chunks without content
        are silently dropped — the caller preserves them in the remaining list.

        Args:
            query: The user query.
            candidates: (chunk_id, rrf_score) tuples to rerank.

        Returns:
            List of ``(chunk_id, raw_cross_encoder_score)`` tuples sorted by
            descending score.  Only chunks that could be scored are returned.
        """
        if not candidates:
            return []

        # Collect chunk texts for candidates
        chunk_texts: list[str] = []
        valid_ids: list[str] = []
        for cid, _ in candidates:
            node = self.graph.nodes.get(cid)
            if node is not None and node.content:
                chunk_texts.append(node.content)
                valid_ids.append(cid)

        if not chunk_texts:
            return []

        # Get cross-encoder model and compute scores
        reranker = await self._get_reranker()
        model = await reranker._ensure_model()  # type: ignore[attr-defined]
        pairs = [(query, text) for text in chunk_texts]
        scores = await asyncio.to_thread(model.predict, pairs)
        scores = [float(s) for s in scores]

        # Sort by descending cross-encoder score
        scored = list(zip(valid_ids, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    async def ingest_graph(
        self,
        graph: ChunkGraph,
        formatter: ChunkTextFormatter | None = None,
        interfaces: list[APIInterface] | None = None,
        enums: list[APIEnum] | None = None,
        error_codes: list[APIErrorCode] | None = None,
    ) -> None:
        """Index a chunk graph in both BM25 and embedding indexes.

        Args:
            graph: The graph to index.
            formatter: Optional text formatter.  If omitted, a default
                       ``ChunkTextFormatter`` is created.
            interfaces: Optional domain objects for rich text formatting.
            enums: Optional domain objects for rich text formatting.
            error_codes: Optional domain objects for rich text formatting.
        """
        # Synchronous BM25 indexing
        self.bm25_index.add_graph(graph)

        # Asynchronous embedding indexing
        if formatter is None:
            from src.domain.rag.api_docs.chunking.text_formatter import (
                ChunkTextFormatter,
            )

            formatter = ChunkTextFormatter()

        await self.embedding_index.add_graph(
            graph,
            formatter,
            interfaces=interfaces,
            enums=enums,
            error_codes=error_codes,
        )
        logger.info(
            "Ingested graph with %d nodes into hybrid retriever",
            len(graph.nodes),
        )
