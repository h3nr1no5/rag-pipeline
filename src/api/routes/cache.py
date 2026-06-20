from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from ..schemas import QueryHistoryItem, QueryHistoryResponse
from ..dependencies import get_db, get_current_user
from ...infrastructure.database.models import User, QueryCache
from ...core.config import get_settings

router = APIRouter(prefix="/query", tags=["Query"])
settings = get_settings()


@router.get("/history", response_model=QueryHistoryResponse)
async def get_query_history(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        delete(QueryCache).where(QueryCache.expires_at < datetime.now(timezone.utc))
    )
    await db.commit()
    
    result = await db.execute(
        select(QueryCache)
        .where(QueryCache.user_id == current_user.id)
        .order_by(QueryCache.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    queries = result.scalars().all()
    
    return QueryHistoryResponse(
        queries=[QueryHistoryItem.model_validate(q) for q in queries],
        total=len(queries),
    )


@router.get("/history/{query_id}", response_model=QueryHistoryItem)
async def get_query_detail(
    query_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(QueryCache).where(
            QueryCache.id == query_id,
            QueryCache.user_id == current_user.id,
        )
    )
    query_cache = result.scalar_one_or_none()
    
    if not query_cache:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    
    if query_cache.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Query response has expired")
    
    return query_cache


@router.delete("/clear", status_code=status.HTTP_204_NO_CONTENT)
async def clear_query_cache(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        delete(QueryCache).where(QueryCache.user_id == current_user.id)
    )
    await db.commit()
    return None
