"""LlamaIndex wrapper for existing Sentence Transformer embeddings."""

import logging

from llama_index.core.embeddings import BaseEmbedding

logger = logging.getLogger(__name__)


class SentenceTransformerEmbedding(BaseEmbedding):
    """LlamaIndex-compatible wrapper around existing SentenceTransformerEmbedder.

    Reuses the existing embedder instance to avoid loading the model twice.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        embedder=None,
        **kwargs
    ):
        super().__init__(model_name=model_name, **kwargs)
        self._custom_embedder = embedder

    @classmethod
    async def from_existing(cls, embedder=None) -> "SentenceTransformerEmbedding":
        """Create wrapper from existing embedder."""
        return cls(embedder=embedder)

    async def _aget_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        """Async batch embedding using existing embedder."""
        if self._custom_embedder is None:
            from ...domain.services.embedding import get_embedder
            self._custom_embedder = await get_embedder()
        return await self._custom_embedder.embed_texts(texts)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        """Async single query embedding."""
        if self._custom_embedder is None:
            from ...domain.services.embedding import get_embedder
            self._custom_embedder = await get_embedder()
        return await self._custom_embedder.embed_text(query)
