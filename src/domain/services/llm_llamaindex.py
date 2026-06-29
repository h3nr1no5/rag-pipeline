"""LlamaIndex wrapper for MLX-LM."""

import logging
from typing import Any

from llama_index.core.llms import LLM, ChatMessage, ChatResponse, CompletionResponse

logger = logging.getLogger(__name__)


class MLXLLMWrapper(LLM):
    """LlamaIndex-compatible wrapper around MLX-LLM."""

    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.5,
        max_tokens: int = 600,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._model: str = model or "mlx-community/qwen2.5-1.5b-instruct-4bit"
        self._temperature: float = temperature
        self._max_tokens: int = max_tokens
        self._mlx_llm: Any = None

    @classmethod
    async def from_existing(cls, llm=None) -> "MLXLLMWrapper":
        """Create wrapper from existing LLM."""
        instance = cls()
        instance._mlx_llm = llm
        return instance

    async def _agenerate(self, prompt: str, **kwargs) -> CompletionResponse:
        """Async generate using MLX-LM."""
        if self._mlx_llm is None:
            from ...domain.services.llm import get_llm
            self._mlx_llm = await get_llm()

        max_tokens = kwargs.get("max_tokens", self._max_tokens)
        temperature = kwargs.get("temperature", self._temperature)

        result = await self._mlx_llm.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        return CompletionResponse(text=result, raw={"model": self._model})

    async def _achat(self, messages: list[ChatMessage], **kwargs) -> ChatResponse:
        """Async chat using MLX-LM."""
        prompt_parts = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else str(msg.role)
            prompt_parts.append(f"{role}: {msg.content}")

        prompt = "\n".join(prompt_parts)
        completion = await self._agenerate(prompt, **kwargs)

        return ChatResponse(
            message=ChatMessage(role="assistant", content=completion.text),
            raw=completion.raw,
        )
