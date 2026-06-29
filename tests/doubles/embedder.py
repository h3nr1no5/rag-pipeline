"""Test double for the Embedder protocol."""

import hashlib
import math

from src.domain.ports.embedder import Embedder


class TestEmbedder(Embedder):
    """Deterministic Embedder test double.

    Produces hash-based vectors using SHA-256 of the input text so that
    every call with the same text returns the same vector.  Vectors are
    non-zero, finite, and pass all downstream validation.
    """

    def __init__(self, dimension: int = 768) -> None:
        """Initialise the test embedder.

        Parameters
        ----------
        dimension : int
            Output vector dimension (default 768, matching all-mpnet-base-v2).
        """
        self._dimension = dimension

    async def embed_text(self, text: str) -> list[float]:
        """Return a deterministic vector derived from *text*."""
        seed = int(hashlib.sha256(text.encode()).hexdigest(), 16)
        return [math.sin(seed + i * 0.1) * 0.1 for i in range(self._dimension)]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed each text in *texts* and return a list of vectors."""
        return [await self.embed_text(t) for t in texts]

    def get_model_name(self) -> str:
        return "test-embedder"

    def get_dimension(self) -> int:
        return self._dimension
