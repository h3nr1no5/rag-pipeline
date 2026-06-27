"""MLX LLM adapter for LlamaIndex.

Wraps the existing ``MLXLLM`` singleton as a LlamaIndex-compatible ``LLM``
so that ``ResponseSynthesizer`` can use the same local MLX-optimized model.
"""

import logging
from collections.abc import Sequence
from typing import Any

from llama_index.core.base.llms.base import BaseLLM
from llama_index.core.base.llms.types import (
    ChatMessage,
    ChatResponse,
    ChatResponseAsyncGen,
    ChatResponseGen,
    CompletionResponse,
    CompletionResponseAsyncGen,
    CompletionResponseGen,
    LLMMetadata,
)
from llama_index.core.bridge.pydantic import Field

from ...core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class MLXLlamaIndexLLM(BaseLLM):
    """Adapter that wraps the project's ``MLXLLM`` singleton for LlamaIndex.

    Delegates ``achat`` / ``stream_chat`` (and their completion counterparts)
    to the existing ``MLXLLM.generate()`` / ``generate_stream()`` methods.
    """

    model_name: str = Field(default=settings.llm_model, description="MLX model name")
    system_prompt: str | None = Field(default=None, description="System prompt for the LLM")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            model_name=self.model_name,
            num_output=settings.llm_max_tokens,
            is_chat_model=True,
        )

    async def achat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        from .llm import get_llm

        prompt = self._messages_to_prompt(messages)
        llm = await get_llm()
        response = await llm.generate(
            prompt,
            max_tokens=kwargs.get("max_tokens", settings.llm_max_tokens),
            temperature=kwargs.get("temperature", settings.llm_temperature),
        )
        return ChatResponse(
            message=ChatMessage(role="assistant", content=response),
        )

    async def astream_chat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponseAsyncGen:
        from .llm import get_llm

        prompt = self._messages_to_prompt(messages)
        llm = await get_llm()

        async def gen() -> ChatResponseAsyncGen:
            async for token in llm.generate_stream(
                prompt,
                max_tokens=kwargs.get("max_tokens", settings.llm_max_tokens),
                temperature=kwargs.get("temperature", settings.llm_temperature),
            ):
                yield ChatResponse(
                    message=ChatMessage(role="assistant", content=token),
                    delta=token,
                )

        return gen()

    async def apredict(self, prompt: str, **kwargs: Any) -> str:
        from .llm import get_llm

        llm = await get_llm()
        response = await llm.generate(
            prompt,
            max_tokens=kwargs.get("max_tokens", settings.llm_max_tokens),
            temperature=kwargs.get("temperature", settings.llm_temperature),
        )
        return response

    async def acomplete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponse:
        from .llm import get_llm

        llm = await get_llm()
        response = await llm.generate(
            prompt,
            max_tokens=kwargs.get("max_tokens", settings.llm_max_tokens),
            temperature=kwargs.get("temperature", settings.llm_temperature),
        )
        return CompletionResponse(text=response)

    async def astream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseAsyncGen:
        from .llm import get_llm

        llm = await get_llm()

        async def gen() -> CompletionResponseAsyncGen:
            async for token in llm.generate_stream(
                prompt,
                max_tokens=kwargs.get("max_tokens", settings.llm_max_tokens),
                temperature=kwargs.get("temperature", settings.llm_temperature),
            ):
                yield CompletionResponse(text=token, delta=token)

        return gen()

    def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        raise NotImplementedError("Use async methods with MLX LLM")

    def stream_chat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponseGen:
        raise NotImplementedError("Use async methods with MLX LLM")

    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        raise NotImplementedError("Use async methods with MLX LLM")

    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponseGen:  # noqa: E501
        raise NotImplementedError("Use async methods with MLX LLM")

    @staticmethod
    def _messages_to_prompt(messages: Sequence[ChatMessage]) -> str:
        parts: list[str] = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            parts.append(f"{role}: {msg.content}")
        return "\n\n".join(parts) + "\n\nassistant:"
