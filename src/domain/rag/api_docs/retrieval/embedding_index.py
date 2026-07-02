"""Embedding-based semantic index for API documentation retrieval.

Task 5.2: ApiEmbeddingIndex implementation.

Wraps the project's shared ``SentenceTransformerEmbedder`` and stores
normalised chunk embeddings in a FAISS ``IndexFlatIP`` for fast cosine
similarity search.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.domain.rag.api_docs.types import ProgressReporter

if TYPE_CHECKING:
    from src.domain.rag.api_docs.chunking.builder import ChunkGraph
    from src.domain.rag.api_docs.chunking.text_formatter import ChunkTextFormatter
    from src.domain.rag.api_docs.model.models import (
        APIEnum,
        APIErrorCode,
        APIInterface,
        APIRecord,
    )
    from src.domain.services.embedding import SentenceTransformerEmbedder

logger = logging.getLogger(__name__)


class ApiEmbeddingIndex:
    """FAISS-based embedding index for API doc chunks.

    Lazy-loads the shared ``SentenceTransformerEmbedder`` on first use and
    normalises all embeddings so that ``IndexFlatIP`` (inner product)
    behaves as cosine similarity.
    """

    def __init__(self) -> None:
        self._embedder: SentenceTransformerEmbedder | None = None
        self._dimension: int = 0

        # FAISS index: ordinal position <-> self.chunk_ids position
        self._index: Any = None  # faiss.Index
        self.chunk_ids: list[str] = []
        self._embeddings_dict: dict[str, list[float]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_graph(
        self, graph: ChunkGraph, formatter: ChunkTextFormatter,
        interfaces: list[APIInterface] | None = None,
        enums: list[APIEnum] | None = None,
        error_codes: list[APIErrorCode] | None = None,
        records: list[APIRecord] | None = None,
        progress_callback: ProgressReporter | None = None,
    ) -> None:
        """Format, embed, and index all chunks from *graph*.

        Args:
            graph: A populated ChunkGraph (``content`` field will be filled
                   in-place by *formatter*).
            formatter: The text formatter to use for converting each chunk
                       into embeddable text.
            interfaces: Optional domain objects for rich text formatting.
            enums: Optional domain objects for rich text formatting.
            error_codes: Optional domain objects for rich text formatting.
            records: Optional record domain objects for rich text formatting.
            progress_callback: Optional progress reporter callback,
                               called with ``(step, message)``.
                               Security: must never accept user-supplied
                               callables — use ``ProgressReporter`` protocol.
        """
        import faiss
        import numpy as np

        embedder = await self._get_embedder()

        if progress_callback:
            await progress_callback.report("indexing", "Formatting graph content…")

        # Only format if content is not already populated (task 1.1)
        needs_format = any(not node.content for node in graph.nodes.values())
        if needs_format:
            formatter.format_graph(graph, interfaces, enums, error_codes, records=records)

        texts: list[str] = []
        ids: list[str] = []
        for node in graph.nodes.values():
            if node.content:
                texts.append(node.content)
                ids.append(node.chunk_id)

        if not texts:
            logger.warning("add_graph called with graph that has no chunk content")
            return

        if progress_callback:
            await progress_callback.report("indexing", f"Embedding {len(texts)} chunks…")

        # Batch-embed
        raw_embeddings = await embedder.embed_texts(texts)

        # Normalise for cosine similarity via IndexFlatIP
        from src.domain.services.embedding import normalize_embedding

        normalized = [normalize_embedding(emb) for emb in raw_embeddings]

        # Capture normalized embeddings for persistence
        self._embeddings_dict = {}
        for chunk_id, emb in zip(ids, normalized):
            self._embeddings_dict[chunk_id] = emb.tolist() if hasattr(emb, 'tolist') else list(emb)

        # Build / extend the FAISS index
        if self._index is None:
            self._index = faiss.IndexFlatIP(self._dimension)

        embedding_array = np.array(normalized, dtype=np.float32)
        self._index.add(embedding_array)
        self.chunk_ids.extend(ids)

        logger.info(
            "Embedding index built: %d vectors (dim=%d, total=%d)",
            len(ids),
            self._dimension,
            self._index.ntotal,
        )

    def load_embeddings(
        self, embeddings: dict[str, list[float]], dimension: int
    ) -> None:
        """Load pre-computed embeddings directly without calling the embedder.

        Creates a new ``faiss.IndexFlatIP(dimension)``, normalises all
        vectors with ``faiss.normalize_L2``, and adds them to the index.

        Args:
            embeddings: Mapping of ``chunk_id`` → embedding vector.
            dimension: Dimensionality of the embedding vectors.
        """
        import faiss
        import numpy as np

        # Reset any previously loaded index
        self.chunk_ids.clear()
        self._dimension = dimension

        # Build vectors in insertion order
        ids: list[str] = []
        vectors: list[np.ndarray] = []
        for chunk_id, vec in embeddings.items():
            ids.append(chunk_id)
            vectors.append(np.array(vec, dtype=np.float32))

        if not vectors:
            logger.warning("load_embeddings called with empty embeddings dict")
            self._index = faiss.IndexFlatIP(dimension)
            return

        embedding_array = np.array(vectors, dtype=np.float32)

        # Normalise for cosine similarity via IndexFlatIP
        faiss.normalize_L2(embedding_array)

        self._index = faiss.IndexFlatIP(dimension)
        self._index.add(embedding_array)
        self.chunk_ids = ids

        logger.info(
            "Loaded %d pre-computed embeddings (dim=%d)",
            len(ids),
            dimension,
        )

    async def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Search the embedding index by semantic similarity.

        Args:
            query: Natural-language query string.
            top_k: Maximum number of results to return.

        Returns:
            List of ``(chunk_id, score)`` tuples sorted by descending cosine
            similarity.  Scores are in [0, 1] for unit-normalised vectors.
            Empty list if the index is empty or the query is blank.
        """
        if self._index is None or self._index.ntotal == 0 or not query.strip():
            return []

        import numpy as np

        embedder = await self._get_embedder()
        from src.domain.services.embedding import normalize_embedding

        raw_query = await embedder.embed_text(query)
        query_vec = normalize_embedding(raw_query)

        k = min(top_k, self._index.ntotal)
        query_array = np.array([query_vec], dtype=np.float32)
        scores_arr, indices_arr = self._index.search(query_array, k)

        results: list[tuple[str, float]] = []
        for score, idx in zip(scores_arr[0], indices_arr[0]):
            if 0 <= idx < len(self.chunk_ids):
                results.append((self.chunk_ids[idx], float(score)))

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_embedder(self) -> SentenceTransformerEmbedder:
        """Lazy-load the shared embedder singleton."""
        if self._embedder is None:
            from src.domain.services.embedding import get_embedder

            self._embedder = await get_embedder()
            self._dimension = self._embedder.get_dimension()
            if self._index is None:
                import faiss

                self._index = faiss.IndexFlatIP(self._dimension)
                logger.debug(
                    "ApiEmbeddingIndex: lazy-loaded embedder (dim=%d)", self._dimension
                )
        return self._embedder
