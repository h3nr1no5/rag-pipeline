from abc import ABC, abstractmethod


class Embedder(ABC):
    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        pass

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        pass
