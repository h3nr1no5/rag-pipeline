from abc import ABC, abstractmethod
from typing import AsyncGenerator

from ..entities import Chunk, RetrievedChunk


class VectorStore(ABC):
    @abstractmethod
    async def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        pass

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        k: int = 5,
        filter_metadata: dict | None = None,
    ) -> list[RetrievedChunk]:
        pass

    @abstractmethod
    async def delete(self, document_id: str) -> None:
        pass

    @abstractmethod
    async def exists(self, document_id: str) -> bool:
        pass
