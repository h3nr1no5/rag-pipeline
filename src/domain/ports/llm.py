from abc import ABC, abstractmethod
from typing import AsyncGenerator


class LLM(ABC):
    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        max_tokens: int = 600,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        pass

    @abstractmethod
    async def generate(self, prompt: str, max_tokens: int = 600, temperature: float = 0.7) -> str:
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        pass
