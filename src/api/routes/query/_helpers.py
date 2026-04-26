"""Helper functions for query routes."""

import re
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import Select

from ...infrastructure.database.models import QueryCache
from ...core.security import generate_cache_key
from ...core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def deduplicate_chunks(chunks: list[tuple["Chunk", float]], threshold: int = 50) -> list[tuple["Chunk", float]]:
    """Remove duplicate chunks based on content signature."""
    if not chunks:
        return []
    
    seen_signatures = []
    unique_chunks = []
    
    for chunk, score in chunks:
        sig = chunk.content[:threshold].lower().strip()
        if sig not in seen_signatures:
            seen_signatures.append(sig)
            unique_chunks.append((chunk, score))
    
    return unique_chunks


def build_prompt(question: str, context_chunks: list[tuple["Chunk", float]]) -> str:
    """Build the prompt for the LLM with context chunks."""
    context_chunks = deduplicate_chunks(context_chunks)[:3]
    
    context_text = "\n\n".join([
        f"SOURCE {i+1}: {chunk.content[:500]}"
        for i, (chunk, _) in enumerate(context_chunks)
    ])
    
    prompt = f"""Answer the question in 2-3 sentences based ONLY on the sources below.

{context_text}

Question: {question}

Answer:"""
    
    return prompt


def clean_response(text: str) -> str:
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
    if text and text[-1] not in '.!?)':
        last_period = text.rfind('. ')
        if last_period > len(text) * 0.5:
            text = text[:last_period + 1]
    
    return text.strip()


async def check_cache(
    db: "AsyncSession",
    document_ids: list[str],
    question: str,
    strategy_id: str,
) -> tuple[QueryCache | None, str]:
    """Check if there's a cached response for the query."""
    cache_key = generate_cache_key(
        document_id=",".join(sorted(document_ids)),
        query_text=question,
        chunking_strategy_id=strategy_id,
        embedding_model=settings.embedding_model,
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