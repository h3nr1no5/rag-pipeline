"""
LangChain QA chain that wraps the existing MLX LLM.
"""
import logging
import time
from collections.abc import AsyncGenerator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult
from langchain_core.runnables import RunnableSequence

from ...core.config import get_settings
from ...core.logging import log_structured
from .prompt_builder import build_prompt
from .retrieval_langchain import LangChainRetriever, RetrievedChunkResult, get_hybrid_retriever

logger = logging.getLogger(__name__)
settings = get_settings()


class MLXChatModel(BaseChatModel):
    """LangChain-compatible wrapper for MLX LLM."""

    def __init__(self):
        self._llm = None
        self._model_loaded = False

    async def _ensure_llm(self):
        """Ensure LLM is loaded."""
        if self._llm is None:
            from .llm import get_llm
            self._llm = await get_llm()

    @property
    def _llm_model(self):
        return self._llm

    @property
    def _identifying_params(self):
        return {"model": settings.llm_model}

    @property
    def _llm_type(self) -> str:
        return "mlx"

    async def _agenerate(
        self,
        messages,
        stop=None,
        **kwargs,
    ):
        """Async generate using MLX LLM."""
        await self._ensure_llm()

        # Convert LangChain messages to prompt
        prompt_parts = []
        for msg in messages:
            if hasattr(msg, "type"):
                if msg.type == "human":
                    prompt_parts.append(f"User: {msg.content}")
                elif msg.type == "ai":
                    prompt_parts.append(f"Assistant: {msg.content}")
                elif msg.type == "system":
                    prompt_parts.append(f"System: {msg.content}")

        prompt = "\n\n".join(prompt_parts) + "\n\nAssistant:"

        # Generate
        if self._llm:
            try:
                response = await self._llm.generate(
                    prompt,
                    max_tokens=kwargs.get("max_tokens", settings.llm_max_tokens),
                    temperature=kwargs.get("temperature", settings.llm_temperature),
                )

                return {
                    "generations": [{
                        "message": AIMessage(content=response),
                        "generation_info": {"finish_reason": "stop"},
                    }],
                    "llm_output": {"model": settings.llm_model},
                }
            except Exception as e:
                logger.error(f"LLM generation failed: {e}")
                raise

        # Fallback
        return {
            "generations": [{
                "message": AIMessage(content="I apologize, but I couldn't generate a response."),
                "generation_info": {"finish_reason": "error"},
            }],
            "llm_output": {"model": settings.llm_model},
        }

    async def agenerate(  # type: ignore[override]
        self,
        messages,
        stop=None,
        **kwargs,
    ) -> LLMResult:
        """Generate a single response."""
        result = await self._agenerate(messages, stop, **kwargs)
        return result["generations"]

    async def agenerate_plus(
        self,
        messages,
        stop=None,
        **kwargs,
    ) -> "LLMResult":
        """Generate multiple responses."""
        return await self._agenerate(messages, stop, **kwargs)

    def _generate(
        self,
        messages,
        stop=None,
        **kwargs,
    ):
        """Sync generate (not supported)."""
        raise NotImplementedError("Use async methods with MLX LLM")





class LangChainQAChain:
    """LangChain QA chain using hybrid retrieval and MLX LLM."""

    def __init__(self):
        self._chat_model: MLXChatModel | None = None
        self._retriever: LangChainRetriever | None = None
        self._chain = None
        self._document_ids: set[str] | None = None

    async def initialize(self, chunks: list, chunk_embeddings: list[list[float]], document_ids: set[str] | None = None) -> None:
        """Initialize the QA chain."""
        start_time = time.time()

        try:
            # Store document IDs for change detection
            self._document_ids = document_ids if document_ids else set(c.document_id for c in chunks)

            # Initialize chat model
            self._chat_model = MLXChatModel()

            # Initialize hybrid retriever
            self._retriever = await get_hybrid_retriever()
            await self._retriever.initialize(chunks, chunk_embeddings)

            # Create a simple chain using RunnableSequence
            # The chain will be: retriever -> prompt -> chat_model
            retrieval_retriever = self._retriever._ensemble if self._retriever._ensemble else None
            if retrieval_retriever:
                self._chain = RunnableSequence(first=retrieval_retriever, last=self._chat_model)

            elapsed = time.time() - start_time
            log_structured("src.domain.services.chain_langchain", "init",
                elapsed_ms=round(elapsed * 1000),
                retriever_initialized=self._retriever is not None and self._retriever.is_initialized(),
                chain_created=self._chain is not None,
            )

        except Exception as e:
            logger.error(f"Failed to initialize QA chain: {type(e).__name__}: {e}", exc_info=True)
            raise

    async def generate_stream(
        self,
        question: str,
        max_tokens: int = 600,
        temperature: float = 0.5,
        prompt_sources: int = 3,
        response_length: str = "normal",
        include_citations: bool = True,
        top_k: int = 5,
        clean_response_enabled: bool = True,
    ) -> AsyncGenerator[tuple[str, list[RetrievedChunkResult]], None]:
        """Generate streaming response with verification.
        
        NOTE: Due to verification, the full response is buffered before yielding.
        This introduces a ~200-500ms latency before the first token.
        """
        if not self._chain:
            logger.warning("QA chain not initialized")
            yield ("I apologize, but the QA chain is not ready.", [])
            return

        try:
            # First get retrieved sources
            if self._retriever:
                sources = await self._retriever.retrieve(question, top_k=top_k)
            else:
                sources = []

            # Deduplicate chunks to avoid duplicate content in prompt
            from .prompt_builder import deduplicate_chunks
            deduped = deduplicate_chunks(sources)
            prompt_sources_slice = deduped[:prompt_sources]

            # Build prompt using shared helper
            prompt = build_prompt(
                question,
                prompt_sources_slice,
                prompt_sources=prompt_sources,
                include_citations=include_citations,
                response_length=response_length
            )

            # Generate (buffered for verification)
            from .llm import get_llm
            llm = await get_llm()

            response = await llm.generate(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            # First verify the raw response (with citations intact)
            from .verification import ResponseVerifier
            verifier = ResponseVerifier()
            verified = await verifier.verify(response, prompt_sources_slice)

            # Then clean the verified text (strip citations if needed, truncate, etc.)
            from .prompt_builder import clean_response
            if clean_response_enabled:
                final_text = clean_response(verified.verified_text, response_length, include_citations)
            else:
                final_text = verified.verified_text

            logger.info(f"Stream verification: {len(verified.unsupported)} unsupported claims, confidence={verified.confidence:.2f}")

            yield (final_text, prompt_sources_slice)

        except Exception as e:
            logger.error(f"Generation failed: {type(e).__name__}: {e}")
            yield ("I apologize, but I couldn't generate a response.", [])

    def is_initialized(self) -> bool:
        return self._chain is not None

    async def generate(
        self,
        question: str,
        max_tokens: int = 600,
        temperature: float = 0.5,
        prompt_sources: int = 3,
        response_length: str = "normal",
        include_citations: bool = False,
        top_k: int = 5,
        clean_response_enabled: bool = True,
    ) -> tuple[str, list[RetrievedChunkResult]]:
        """Generate full response with verification."""
        if not self._chain:
            return ("I apologize, but the QA chain is not ready.", [])

        try:
            # Get retrieved sources
            if self._retriever:
                sources = await self._retriever.retrieve(question, top_k=top_k)
            else:
                sources = []

            # Deduplicate chunks to avoid duplicate content in prompt
            from .prompt_builder import deduplicate_chunks
            deduped = deduplicate_chunks(sources)
            prompt_sources_slice = deduped[:prompt_sources]

            # Build prompt using shared helper
            prompt = build_prompt(
                question,
                prompt_sources_slice,
                prompt_sources=prompt_sources,
                include_citations=include_citations,
                response_length=response_length
            )

            # Generate
            from .llm import get_llm
            llm = await get_llm()

            response = await llm.generate(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            # First verify the raw response (with citations intact)
            from .verification import ResponseVerifier
            verifier = ResponseVerifier()
            verified = await verifier.verify(response, prompt_sources_slice)

            # Then clean the verified text (strip citations if needed, truncate, etc.)
            from .prompt_builder import clean_response
            if clean_response_enabled:
                final_text = clean_response(verified.verified_text, response_length, include_citations)
            else:
                final_text = verified.verified_text

            logger.info(f"Verification: {len(verified.unsupported)} unsupported claims, confidence={verified.confidence:.2f}")

            return (final_text, prompt_sources_slice)

        except Exception as e:
            logger.error(f"Generation failed: {type(e).__name__}: {e}")
            return ("I apologize, but I couldn't generate a response.", [])

    def get_document_ids(self) -> set[str] | None:
        return self._document_ids


# Global instance
_qa_chain_instance: LangChainQAChain | None = None


async def get_qa_chain() -> LangChainQAChain:
    """Get or create the global QA chain instance."""
    global _qa_chain_instance
    if _qa_chain_instance is None:
        _qa_chain_instance = LangChainQAChain()
    return _qa_chain_instance


async def build_qa_chain(
    chunks: list,
    chunk_embeddings: list[list[float]],
) -> LangChainQAChain:
    """Build and initialize the QA chain."""
    chain = await get_qa_chain()
    await chain.initialize(chunks, chunk_embeddings)
    return chain


def reset_qa_chain() -> None:
    """Reset the QA chain instance."""
    global _qa_chain_instance
    logger.info("Resetting QA chain")
    _qa_chain_instance = None
