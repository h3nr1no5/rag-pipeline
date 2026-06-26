import os
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ...core.config import get_settings
from .models import Base

settings = get_settings()

_database_url = (os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL") or
                 settings.database_url)

_connect_args: dict[str, Any] = {"check_same_thread": False}
if "sqlite" in _database_url:
    _connect_args["timeout"] = 60

engine = create_async_engine(
    _database_url,
    connect_args=_connect_args,
    poolclass=StaticPool,
    echo=False,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def ensure_db():
    # Create tables if they do not exist, do not drop existing data
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
