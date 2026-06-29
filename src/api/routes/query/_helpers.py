"""Helper functions for query routes."""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from ....core.config import get_settings
from ....core.security import generate_cache_key
from ....domain.services import prompt_builder as _pb
from ....infrastructure.database.models import QueryCache

# Re-export prompt builder functions from domain layer
# This maintains backward compatibility for API layer imports
build_prompt = _pb.build_prompt
clean_response = _pb.clean_response
deduplicate_chunks = _pb.deduplicate_chunks

logger = logging.getLogger(__name__)
settings = get_settings()


async def check_cache(
    db: "AsyncSession",
    document_ids: list[str],
    question: str,
    strategy_id: str,
    include_citations: bool = True,
    response_length: str = "normal",
    link_decay_factor: float = 0.85,
    link_expansion_factor: int = 2,
    clean_response: bool = True,
) -> tuple[QueryCache | None, str]:
    """Check if there's a cached response for the query."""
    cache_key = generate_cache_key(
        document_id=",".join(sorted(document_ids)),
        query_text=question,
        chunking_strategy_id=strategy_id,
        embedding_model=settings.embedding_model,
        include_citations=str(include_citations),
        response_length=response_length,
        link_decay_factor=str(link_decay_factor),
        link_expansion_factor=str(link_expansion_factor),
        clean_response=str(clean_response),
    )

    # If cache expiry is 0 or less, skip caching entirely
    if settings.cache_expiry_days <= 0:
        return None, cache_key

    from sqlalchemy import select
    result = await db.execute(
        select(QueryCache).where(
            QueryCache.query_hash == cache_key,
            QueryCache.expires_at > datetime.now(UTC),
        )
    )
    cached = result.scalar_one_or_none()

    return cached, cache_key
