"""BM25 keyword index for API documentation retrieval.

Task 5.1: ApiBm25Index implementation.

Indexes function names, parameter names, type names, and error code names
from a ChunkGraph for exact-match keyword retrieval using BM25Okapi.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.rag.api_docs.chunking.builder import ChunkGraph
    from src.domain.rag.api_docs.chunking.graph import ChunkNode

logger = logging.getLogger(__name__)


class ApiBm25Index:
    """BM25 keyword index over API documentation chunk names.

    Builds a BM25Okapi corpus from the identifying names and type annotations
    of each chunk.  Also maintains a term → chunk_ids map for exact-match
    lookups.

    Attributes:
        chunk_ids: Corpus-order list of chunk_ids (parallel to BM25 internal doc list).
        term_to_chunk_ids: Mapping of lowercase term → set of chunk_ids.
    """

    def __init__(self) -> None:
        self.chunk_ids: list[str] = []
        self.term_to_chunk_ids: dict[str, set[str]] = {}
        self._bm25: Any = None  # BM25Okapi instance
        self._corpus: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_graph(self, graph: ChunkGraph) -> None:
        """Index all chunks from *graph* into BM25.

        Args:
            graph: A populated ChunkGraph whose nodes will be indexed.
        """
        if not graph.nodes:
            logger.warning("add_graph called with empty graph — nothing to index")
            return

        from rank_bm25 import BM25Okapi

        self.chunk_ids.clear()
        self._corpus.clear()
        self.term_to_chunk_ids.clear()

        for node in graph.nodes.values():
            keyword_text = self._build_keyword_text(node)
            self._corpus.append(keyword_text)
            self.chunk_ids.append(node.chunk_id)

            # Build inverted term → chunk_ids mapping (lowercased)
            for term in keyword_text.lower().split():
                self.term_to_chunk_ids.setdefault(term, set()).add(node.chunk_id)

        tokenized_corpus = [text.lower().split() for text in self._corpus]
        self._bm25 = BM25Okapi(tokenized_corpus)
        logger.info(
            "BM25 index built: %d documents, %d unique terms",
            len(self.chunk_ids),
            len(self.term_to_chunk_ids),
        )

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Search the BM25 index.

        Args:
            query: Free-text query (lowercased internally for matching).
            top_k: Maximum number of results to return.

        Returns:
            List of ``(chunk_id, score)`` tuples sorted by descending score,
            with scores normalized to [0, 1].  Empty list if the index is
            empty or the query is blank.
        """
        if self._bm25 is None or not query.strip():
            return []

        query_tokens = query.lower().split()
        scores = self._bm25.get_scores(query_tokens)

        # Pair chunk_ids with scores
        results: list[tuple[str, float]] = list(
            zip(self.chunk_ids, [float(s) for s in scores])
        )
        # Sort descending by score
        results.sort(key=lambda x: x[1], reverse=True)

        # Normalise scores to [0, 1]
        if results and results[0][1] > 0:
            max_score = results[0][1]
            results = [(cid, s / max_score) for cid, s in results]

        return results[:top_k]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_keyword_text(node: ChunkNode) -> str:
        """Assemble a keyword-rich text fragment from the node's metadata.

        The text is composed of the identifying names and type annotations
        relevant to each chunk kind — matching the spec requirement to index
        *function names, parameter names, type names, and error code names*.
        """
        m = node.metadata
        parts: list[str] = []

        kind = node.kind

        if kind == "interface":
            parts.append(m.get("interface_name", ""))

        elif kind == "method":
            parts.append(m.get("interface_name", ""))
            parts.append(m.get("function_name", ""))
            parts.append(m.get("name", ""))
            parts.append(m.get("return_type", ""))

        elif kind == "parameter":
            parts.append(m.get("interface_name", ""))
            parts.append(m.get("function_name", ""))
            parts.append(m.get("name", ""))
            parts.append(m.get("type_annotation", ""))

        elif kind == "property":
            parts.append(m.get("interface_name", ""))
            parts.append(m.get("name", ""))
            parts.append(m.get("type_annotation", ""))

        elif kind == "enum":
            parts.append(m.get("type_name", ""))
            parts.append(m.get("enum_values", ""))

        elif kind == "enum_value":
            parts.append(m.get("type_name", ""))
            parts.append(m.get("name", ""))

        elif kind == "error_code":
            parts.append(m.get("name", ""))
            parts.append(m.get("code", ""))

        elif kind == "section":
            # PDF-fallback sections use the content directly
            content = node.content or ""
            if content:
                parts.append(content)
            else:
                parts.append(m.get("name", ""))

        # Include description for all chunk kinds
        parts.append(m.get("description", ""))

        # Exclude empty parts
        return " ".join(p.strip() for p in parts if p.strip())
