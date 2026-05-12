"""
LangChain QA chain that wraps the existing MLX LLM.
"""
import logging
import time
from typing import AsyncGenerator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from langchain_core.runnables import RunnableSequence

from langchain_core.outputs import ChatGeneration, LLMResult

from ...core.config import get_settings
from .prompt_builder import build_prompt
from .retrieval_langchain import LangChainRetriever, get_hybrid_retriever

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
    
    async def agenerate(
        self,
        messages,
        stop=None,
        **kwargs,
    ) -> "ChatGeneration":
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
        logger.info("Initializing LangChain QA chain")
        
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
            logger.info(f"LangChain QA chain initialized in {elapsed:.2f}s")
            
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
    ) -> AsyncGenerator[tuple[str, list], None]:
        """Generate streaming response."""
        if not self._chain:
            logger.warning("QA chain not initialized")
            yield ("I apologize, but the QA chain is not ready.", [])
            return
        
        try:
            # First get retrieved sources
            if self._retriever:
                sources = await self._retriever.retrieve(question, top_k=5)
            else:
                sources = []
            
            # Build prompt using shared helper (includes anti-repetition instructions)
            prompt = build_prompt(
                question, 
                sources[:prompt_sources], 
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
            
            yield (response, sources)
            
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
    ) -> tuple[str, list]:
        """Generate full response."""
        if not self._chain:
            return ("I apologize, but the QA chain is not ready.", [])
        
        try:
            # Get retrieved sources
            if self._retriever:
                sources = await self._retriever.retrieve(question, top_k=5)
            else:
                sources = []
            
            # Build prompt using shared helper (includes anti-repetition instructions)
            prompt = build_prompt(
                question, 
                sources[:prompt_sources], 
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
            
            return (response, sources)
            
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