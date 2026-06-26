import atexit
import glob
import os
import uuid

import pytest
import pytest_asyncio
from dotenv import dotenv_values

# Disable DSPy pipeline in tests — the DSPy module uses asyncio.run()
# internally which is incompatible with pytest-asyncio's running event loop.
os.environ["API_DOCS_DSPY_ENABLED"] = "false"
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

_env = dotenv_values(".env")
_raw = _env.get("CACHE_EXPIRY_DAYS")
_cache_expiry_days = int(_raw) if _raw is not None else 3
skipif_no_cache = pytest.mark.skipif(
    _cache_expiry_days <= 0,
    reason="CACHE_EXPIRY_DAYS=0: caching disabled"
)


_test_db_counter = 0
_test_db_paths = []


def _cleanup_test_artifacts():
    for db_path in _test_db_paths:
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
        except Exception:
            pass

    for pattern in ["test_integration_db_*.sqlite", "test_db_*.sqlite", "test_clear_embeddings_db_*.sqlite", "test_chat_db_*.sqlite", "test_chat_e2e_db_*.sqlite", "test_llm_db_*.sqlite"]:
        for f in glob.glob(f"./data/{pattern}"):
            try:
                os.remove(f)
            except Exception:
                pass

    uploads_dir = "./data/uploads"
    if os.path.exists(uploads_dir):
        for f in os.listdir(uploads_dir):
            fpath = os.path.join(uploads_dir, f)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except Exception:
                pass


atexit.register(_cleanup_test_artifacts)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    _cleanup_test_artifacts()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    pass


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    global _test_db_counter
    _test_db_counter += 1

    test_db_url = f"sqlite+aiosqlite:///./data/test_integration_db_{_test_db_counter}_{uuid.uuid4().hex[:8]}.sqlite"
    db_path = test_db_url.replace("sqlite+aiosqlite:///", "")
    _test_db_paths.append(db_path)
    os.environ["TEST_DATABASE_URL"] = test_db_url

    from src.infrastructure.database import session as db_session
    original_engine = db_session.engine
    original_session_maker = db_session.async_session_maker

    new_engine = create_async_engine(
        test_db_url,
        connect_args={"check_same_thread": False, "timeout": 60},
        poolclass=StaticPool,
        echo=False,
    )

    new_session_maker = async_sessionmaker(
        new_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    db_session.engine = new_engine
    db_session.async_session_maker = new_session_maker

    from src.infrastructure.database import session as session_module
    session_module.async_session_maker = new_session_maker

    from src.domain.services import processor
    processor.async_session_maker = new_session_maker

    from src.infrastructure.database.models import Base
    async with new_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from src.core.config import get_settings
    settings = get_settings()

    async with new_session_maker() as session:
        from src.infrastructure.database.models import ChunkingStrategy
        recursive_strategy = ChunkingStrategy(
            id="recursive",
            name="Recursive",
            description="Recursive chunking for general documents",
            chunk_size=settings.default_chunk_size,
            chunk_overlap=settings.default_chunk_overlap,
            separators=["\n\n", "\n", ". "],
            embedding_model=settings.embedding_model,
            is_system=True,
        )
        session.add(recursive_strategy)

        api_strategy = ChunkingStrategy(
            id="semantic",
            name="Semantic Chunking",
            description="Semantic chunking for structured content with optional hyperlink support",
            chunk_size=300,
            chunk_overlap=30,
            separators=["\n## ", "\n### ", "\n", "## ", "### "],
            embedding_model=settings.embedding_model,
            use_hyperlinks=False,
            is_system=True,
        )
        session.add(api_strategy)

        api_docs_strategy = ChunkingStrategy(
            id="api-docs",
            name="API Documentation",
            description="Specialized chunking for API documentation files (DOCX/PDF)",
            chunk_size=settings.default_chunk_size,
            chunk_overlap=settings.default_chunk_overlap,
            separators=["\n\n", "\n", ". "],
            embedding_model=settings.embedding_model,
            use_hyperlinks=False,
            is_system=True,
            engine_type="api-docs",
        )
        session.add(api_docs_strategy)
        await session.commit()

    yield

    db_session.engine = original_engine

    from src.infrastructure.database import session as session_module
    session_module.async_session_maker = original_session_maker

    from src.domain.services import processor
    processor.async_session_maker = original_session_maker

    db_session.async_session_maker = original_session_maker
    await new_engine.dispose()

    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


@pytest.fixture(scope="function", autouse=True)
def clean_uploads_dir():
    """Remove all files from ./data/uploads/ before each test."""
    uploads_dir = "./data/uploads"
    if os.path.exists(uploads_dir):
        for f in os.listdir(uploads_dir):
            fpath = os.path.join(uploads_dir, f)
            try:
                if os.path.isfile(fpath) or os.path.islink(fpath):
                    os.remove(fpath)
            except Exception:
                pass
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def cancel_background_tasks():
    """Cancel and await any pending asyncio tasks created by the processor."""
    yield
    import asyncio

    # Give tasks a moment to settle
    await asyncio.sleep(0)

    tasks = [t for t in asyncio.all_tasks()
             if t is not asyncio.current_task()
             and not t.done()]

    if tasks:
        for t in tasks:
            t.cancel()
        # Wait for cancellation with 5-second timeout
        await asyncio.wait(tasks, timeout=5.0, return_when=asyncio.ALL_COMPLETED)
