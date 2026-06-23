"""Hybrid retriever orchestrating BM25, embedding, RRF, link traversal,
and parent expansion for API documentation.

Task 5.6: HybridRetriever implementation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.domain.rag.api_docs.retrieval.link_traverser import LinkTraverser
from src.domain.rag.api_docs.retrieval.parent_expander import ParentExpander
from src.domain.rag.api_docs.retrieval.rrf import RrfFusion

if TYPE_CHECKING:
    from src.domain.rag.api_docs.chunking.builder import ChunkGraph
    from src.domain.rag.api_docs.chunking.graph import ChunkNode
    from src.domain.rag.api_docs.chunking.text_formatter import ChunkTextFormatter
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
    ) -> None:
        self.bm25_index = bm25_index
        self.embedding_index = embedding_index
        self.graph = graph
        self._rrf = RrfFusion(k=60)
        self._link_traverser = LinkTraverser()
        self._parent_expander = ParentExpander()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def retrieve(self, query: str, top_k: int = 10) -> list[tuple[ChunkNode, float]]:
        """Run the full hybrid retrieval pipeline.

        Args:
            query: Free-text or keyword query.
            top_k: Target number of results (used as a target — the final
                   list may be larger after link traversal / parent expansion).

        Returns:
            List of ``(ChunkNode, rrf_score)`` tuples sorted by descending
            RRF score.  Chunks not found in the graph are silently skipped.
        """
        # 1 & 2: Search both indexes (double top_k for intermediate fusion)
        bm25_results = self.bm25_index.search(query, top_k=top_k * 2)
        embedding_results = await self.embedding_index.search(query, top_k=top_k * 2)

        # 3: Fuse with RRF
        fused = self._rrf.fuse([bm25_results, embedding_results])

        # 4: Take the requested top_k from fused results
        top_chunk_ids = [doc_id for doc_id, _ in fused[:top_k]]

        # 5: Link traversal
        expanded_ids = self._link_traverser.traverse(top_chunk_ids, self.graph)

        # 6: Parent expansion
        final_ids = self._parent_expander.expand(expanded_ids, self.graph)

        # 7: Deduplicate while preserving order
        seen: set[str] = set()
        ordered_ids: list[str] = []
        for cid in final_ids:
            if cid not in seen:
                seen.add(cid)
                ordered_ids.append(cid)

        # 8: Build (ChunkNode, score) tuples
        score_map = dict(fused)
        results: list[tuple[ChunkNode, float]] = []
        for cid in ordered_ids:
            node = self.graph.nodes.get(cid)
            if node is not None:
                score = score_map.get(cid, 0.0)
                results.append((node, score))

        logger.info(
            "HybridRetrieve: query=%r top_k=%d → %d bm25 / %d embed → fused=%d "
            "→ expanded=%d final=%d",
            query,
            top_k,
            len(bm25_results),
            len(embedding_results),
            len(fused),
            len(expanded_ids),
            len(results),
        )
        return results

    async def ingest_graph(
        self,
        graph: ChunkGraph,
        formatter: ChunkTextFormatter | None = None,
    ) -> None:
        """Index a chunk graph in both BM25 and embedding indexes.

        Args:
            graph: The graph to index.
            formatter: Optional text formatter.  If omitted, a default
                       ``ChunkTextFormatter`` is created.
        """
        # Synchronous BM25 indexing
        self.bm25_index.add_graph(graph)

        # Asynchronous embedding indexing
        if formatter is None:
            from src.domain.rag.api_docs.chunking.text_formatter import (
                ChunkTextFormatter,
            )

            formatter = ChunkTextFormatter()

        await self.embedding_index.add_graph(graph, formatter)
        logger.info(
            "Ingested graph with %d nodes into hybrid retriever",
            len(graph.nodes),
        )
