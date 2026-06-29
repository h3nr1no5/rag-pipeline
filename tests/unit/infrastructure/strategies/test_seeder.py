"""Unit tests for YAML strategy seeder (Tasks 9.1, 9.2, 9.3).

Tests for:
- load_strategies_from_yaml(): valid yaml, missing file, invalid yaml, missing key
- seed_strategies_from_yaml(): upsert, skip non-system, graceful fallback
"""

from unittest.mock import mock_open, patch

import pytest_asyncio
import yaml

from src.infrastructure.strategies.seeder import (
    load_strategies_from_yaml,
    seed_strategies_from_yaml,
)

# ---------------------------------------------------------------------------
# Task 9.1 — load_strategies_from_yaml()
# ---------------------------------------------------------------------------


def test_load_valid_yaml():
    """Valid YAML file with strategies list returns parsed data."""
    yaml_content = yaml.dump({
        "strategies": [
            {
                "engine_type": "recursive",
                "name": "Recursive",
                "chunk_size": 1000,
                "chunk_overlap": 200,
            }
        ]
    })
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        result = load_strategies_from_yaml("/fake/path.yaml")
    assert result is not None
    assert "strategies" in result
    assert len(result["strategies"]) == 1
    assert result["strategies"][0]["engine_type"] == "recursive"


def test_load_missing_file():
    """Missing file returns None (no exception raised)."""
    result = load_strategies_from_yaml("/nonexistent/path.yaml")
    assert result is None


def test_load_invalid_yaml():
    """Invalid YAML content returns None."""
    with patch("builtins.open", mock_open(read_data="::: invalid yaml ::{{{")):
        result = load_strategies_from_yaml("/fake/path.yaml")
    assert result is None


def test_load_missing_strategies_key():
    """YAML without 'strategies' key returns None."""
    yaml_content = yaml.dump({"some_other_key": ["value"]})
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        result = load_strategies_from_yaml("/fake/path.yaml")
    assert result is None


def test_load_strategies_not_a_list():
    """YAML with 'strategies' that is not a list returns None."""
    yaml_content = yaml.dump({"strategies": "not a list"})
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        result = load_strategies_from_yaml("/fake/path.yaml")
    assert result is None


def test_load_empty_strategies_list():
    """Empty strategies list is still valid."""
    yaml_content = yaml.dump({"strategies": []})
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        result = load_strategies_from_yaml("/fake/path.yaml")
    assert result is not None
    assert result["strategies"] == []


# ---------------------------------------------------------------------------
# Task 9.2 — seed_strategies_from_yaml()
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite session with the ChunkingStrategy table."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


    # Use aiosqlite with in-memory
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        from src.infrastructure.database.models import Base
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


class FakeSettings:
    embedding_model = "test-embedding-model"


def _make_valid_yaml(strategies_data: list[dict]) -> str:
    return yaml.dump({"strategies": strategies_data})


@patch("src.infrastructure.strategies.seeder.load_strategies_from_yaml")
async def test_seed_creates_new_strategies(mock_load, db_session):
    """Upsert creates new strategies when none exist."""
    mock_load.return_value = {
        "strategies": [
            {
                "engine_type": "recursive",
                "name": "Recursive",
                "chunk_size": 1000,
                "chunk_overlap": 200,
                "separators": ["\n\n", "\n", ". "],
                "use_hyperlinks": False,
                "is_system": True,
            }
        ]
    }
    settings = FakeSettings()
    count = await seed_strategies_from_yaml(db_session, "/fake.yaml", settings)
    assert count == 1

    from sqlalchemy import select

    from src.infrastructure.database.models import ChunkingStrategy
    result = await db_session.execute(select(ChunkingStrategy))
    strategies = result.scalars().all()
    assert len(strategies) == 1
    assert strategies[0].name == "Recursive"
    assert strategies[0].chunk_size == 1000


@patch("src.infrastructure.strategies.seeder.load_strategies_from_yaml")
async def test_seed_updates_existing_strategy(mock_load, db_session):
    """Upsert updates existing strategy with same name."""
    from sqlalchemy import select

    from src.infrastructure.database.models import ChunkingStrategy

    # Pre-create a strategy
    existing = ChunkingStrategy(
        id="recursive",
        name="Recursive",
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n"],
        embedding_model="old-model",
        engine_type="recursive",
        is_system=True,
    )
    db_session.add(existing)
    await db_session.commit()

    mock_load.return_value = {
        "strategies": [
            {
                "engine_type": "recursive",
                "name": "Recursive",
                "chunk_size": 1000,
                "chunk_overlap": 200,
                "separators": ["\n\n", "\n", ". "],
                "use_hyperlinks": True,
                "is_system": True,
            }
        ]
    }
    settings = FakeSettings()
    count = await seed_strategies_from_yaml(db_session, "/fake.yaml", settings)
    assert count == 1

    # Verify the existing strategy was updated
    result = await db_session.execute(
        select(ChunkingStrategy).where(ChunkingStrategy.name == "Recursive")
    )
    updated = result.scalar_one()
    assert updated.chunk_size == 1000
    assert updated.chunk_overlap == 200
    assert updated.use_hyperlinks is True
    assert updated.embedding_model == "test-embedding-model"


@patch("src.infrastructure.strategies.seeder.load_strategies_from_yaml")
async def test_seed_skips_non_system_strategies(mock_load, db_session):
    """Strategies with is_system: false are skipped."""
    mock_load.return_value = {
        "strategies": [
            {
                "engine_type": "custom",
                "name": "Custom",
                "chunk_size": 500,
                "is_system": False,
            },
            {
                "engine_type": "recursive",
                "name": "Recursive",
                "chunk_size": 1000,
                "is_system": True,
            },
        ]
    }
    settings = FakeSettings()
    count = await seed_strategies_from_yaml(db_session, "/fake.yaml", settings)
    # Only the system strategy should be counted
    assert count == 1

    from sqlalchemy import select

    from src.infrastructure.database.models import ChunkingStrategy
    result = await db_session.execute(select(ChunkingStrategy))
    strategies = result.scalars().all()
    assert len(strategies) == 1
    assert strategies[0].name == "Recursive"


@patch("src.infrastructure.strategies.seeder.load_strategies_from_yaml")
async def test_seed_updates_by_id_fallback(mock_load, db_session):
    """Backward-compatible lookup by id when name doesn't match."""
    from sqlalchemy import select

    from src.infrastructure.database.models import ChunkingStrategy

    # Pre-create with a different name but same id
    existing = ChunkingStrategy(
        id="recursive",
        name="Old Recursive",
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n"],
        embedding_model="old-model",
        engine_type="recursive",
        is_system=True,
    )
    db_session.add(existing)
    await db_session.commit()

    mock_load.return_value = {
        "strategies": [
            {
                "engine_type": "recursive",
                "name": "Recursive",
                "chunk_size": 1000,
                "chunk_overlap": 200,
                "separators": ["\n\n"],
                "use_hyperlinks": False,
                "is_system": True,
            }
        ]
    }
    settings = FakeSettings()
    count = await seed_strategies_from_yaml(db_session, "/fake.yaml", settings)
    assert count == 1

    result = await db_session.execute(
        select(ChunkingStrategy).where(ChunkingStrategy.id == "recursive")
    )
    updated = result.scalar_one()
    assert updated.name == "Recursive"  # Name was updated
    assert updated.chunk_size == 1000


@patch("src.infrastructure.strategies.seeder.load_strategies_from_yaml")
async def test_seed_skips_entry_without_engine_type(mock_load, db_session):
    """Entry missing engine_type is skipped with a warning."""
    mock_load.return_value = {
        "strategies": [
            {
                "name": "NoEngineType",
                "chunk_size": 500,
            }
        ]
    }
    settings = FakeSettings()
    count = await seed_strategies_from_yaml(db_session, "/fake.yaml", settings)
    assert count == 0


@patch("src.infrastructure.strategies.seeder.load_strategies_from_yaml")
async def test_seed_handles_config_column(mock_load, db_session):
    """Config dict is persisted correctly."""
    mock_load.return_value = {
        "strategies": [
            {
                "engine_type": "api-docs",
                "name": "API Docs",
                "config": {
                    "max_depth": 3,
                    "format_style": "compact",
                },
                "is_system": True,
            }
        ]
    }
    settings = FakeSettings()
    count = await seed_strategies_from_yaml(db_session, "/fake.yaml", settings)
    assert count == 1

    from sqlalchemy import select

    from src.infrastructure.database.models import ChunkingStrategy
    result = await db_session.execute(select(ChunkingStrategy))
    strategy = result.scalars().one()
    assert strategy.config == {"max_depth": 3, "format_style": "compact"}


# ---------------------------------------------------------------------------
# Task 9.3 — Graceful fallback when YAML missing
# ---------------------------------------------------------------------------


async def test_seed_returns_zero_when_yaml_nonexistent():
    """seed_strategies_from_yaml returns 0 and does not crash when file missing."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        from src.infrastructure.database.models import Base
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        settings = FakeSettings()
        # A path that definitely doesn't exist
        count = await seed_strategies_from_yaml(session, "/definitely/does/not/exist.yaml", settings)  # noqa: E501
        assert count == 0

    await engine.dispose()
