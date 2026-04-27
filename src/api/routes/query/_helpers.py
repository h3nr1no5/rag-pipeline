"""Helper functions for query routes."""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from ....infrastructure.database.models import QueryCache
from ....core.security import generate_cache_key
from ....core.config import get_settings

# Re-export prompt builder functions from domain layer
# This maintains backward compatibility for API layer imports
from ....domain.services.prompt_builder import deduplicate_chunks, build_prompt, clean_response

logger = logging.getLogger(__name__)
settings = get_settings()


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