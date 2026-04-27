"""Helper functions for query routes."""

import re
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import Select

from ....infrastructure.database.models import QueryCache
from ....core.security import generate_cache_key
from ....core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def deduplicate_chunks(chunks: list, threshold: int = 50) -> list:
    """Remove duplicate chunks based on content signature.

    Handles both:
    - Tuples: (Chunk, float) - from cosine retrieval
    - RetrievedChunkResult/LlamaIndexRetrievedChunk objects - from LangChain/LlamaIndex
    """
    if not chunks:
        return []

    seen_signatures = []
    unique_chunks = []

    for item in chunks:
        # Extract content based on type
        if hasattr(item, 'content'):  # RetrievedChunkResult, LlamaIndexRetrievedChunk
            content = item.content
            score = getattr(item, 'score', 0.0)
        else:  # Tuple (Chunk, float)
            content = item[0].content
            score = item[1]

        sig = content[:threshold].lower().strip()
        if sig not in seen_signatures:
            seen_signatures.append(sig)
            # Keep original item type (if tuple, keep tuple; if object, keep object)
            if hasattr(item, 'content'):
                unique_chunks.append(item)
            else:
                unique_chunks.append((item[0], score))

    return unique_chunks


def build_prompt(question: str, context_chunks: list[tuple["Chunk", float]], prompt_sources: int = 3, include_citations: bool = True, response_length: str = "normal") -> str:
    """Build the prompt for the LLM with context chunks."""
    context_chunks = deduplicate_chunks(context_chunks)[:prompt_sources]

    def _extract_chunk_content(item):
        if hasattr(item, 'content'):  # Has .content attribute (RetrievedChunkResult)
            return item.content
        else:  # Tuple (Chunk, float)
            return item[0].content

    # Handle both tuple (Chunk, float) and RetrievedChunkResult objects
    context_list = []
    for item in context_chunks:
        if hasattr(item, 'content'):  # RetrievedChunkResult or similar
            context_list.append(item.content)
        else:  # Tuple (Chunk, float)
            context_list.append(item[0].content)

    context_text = "\n\n".join([
        f"[Source {i+1}]: {content}"
        for i, content in enumerate(context_list)
    ])
    
    citation_instruction = (
        "Cite the source number when making factual claims. "
        if include_citations else ""
    )
    
    # Set verbosity based on response_length
    verbosity = {
        "concise": "Be very brief (1-2 sentences).",
        "normal": "Give a clear, balanced response of appropriate length.",
        "detailed": "Provide a thorough and comprehensive answer with examples where possible."
    }.get(response_length, "")

    prompt = f"""You are a helpful assistant. Answer questions based ONLY on the provided sources below.
If the answer cannot be determined from the sources, say "I don't have enough information to answer this question."
{citation_instruction}{verbosity}

{context_text}

Question: {question}

Answer:"""
    
    if prompt:
        logger.debug(f"Prompt ({len(prompt)} chars): {prompt[:500]}{'...' if len(prompt) > 500 else ''}")
    else:
        logger.debug("Prompt: (empty or None)")
    
    return prompt


def clean_response(text: str, response_length: str = "normal", include_citations: bool = True) -> str:
    """Clean LLM response by removing special tokens and artifacts."""
    text = text.replace("<|endoftext|>", "")
    text = text.replace("<|eos|>", "")
    text = text.replace("<|eot|>", "")
    text = text.replace("<|end|>", "")
    
    text = text.split("<|")[0] if "<|" in text else text
    text = text.strip()
    
    for token in ["[INST]", "[/INST]", "[SYS]", "[/SYS]", "<<SYS>>", "<</SYS>>"]:
        if token in text:
            text = text.split(token)[-1]
    
    for marker in ["Human:", "human:", "Assistant:", "assistant:", "Question:", "Answer:", "Sources:"]:
        if marker in text:
            text = text.split(marker)[0]
    
    text = text.split("You Can Ask")[0].strip()
    text = text.split("Test Questions")[0].strip()
    text = text.split("Examples:")[0].strip()
    text = text.split("Key Points:")[0].strip()
    
    # Only strip citations if they weren't requested
    if not include_citations:
        text = re.sub(r'\[Source \d+\].*?(?=\.|$)', '[Source]', text)
    
    lines = text.split("\n")
    unique_lines = []
    seen = set()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        line_key = line.lower()[:40]
        is_dup = any(line_key in s or s in line_key for s in seen)
        if len(line) > 10 and not is_dup:
            seen.add(line_key)
            unique_lines.append(line)
    
    text = " ".join(unique_lines)
    
    text = re.sub(r'(.{20,})\1{2,}', r'\1', text)
    
    text = text.strip()

    # Only truncate sentences for "concise" mode
    if response_length == "concise" and text and text[-1] not in '.!?)':
        last_period = text.rfind('. ')
        if last_period > 0:
            # Find second-to-last period for 1-2 sentences
            second_last = text.rfind('. ', last_period - 1)
            if second_last > 0:
                text = text[:second_last + 1]
            else:
                text = text[:last_period + 1]
    elif response_length == "detailed":
        # Don't truncate at all - return full response
        pass  # Keep as-is

    return text.strip()


async def check_cache(
    db: "AsyncSession",
    document_ids: list[str],
    question: str,
    strategy_id: str,
    include_citations: bool = True,
    response_length: str = "normal",
) -> tuple[QueryCache | None, str]:
    """Check if there's a cached response for the query."""
    cache_key = generate_cache_key(
        document_id=",".join(sorted(document_ids)),
        query_text=question,
        chunking_strategy_id=strategy_id,
        embedding_model=settings.embedding_model,
        include_citations=str(include_citations),
        response_length=response_length,
    )
    
    from sqlalchemy import select
    result = await db.execute(
        select(QueryCache).where(
            QueryCache.query_hash == cache_key,
            QueryCache.expires_at > datetime.now(timezone.utc),
        )
    )
    cached = result.scalar_one_or_none()
    
    return cached, cache_key