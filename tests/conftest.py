import pytest
import pytest_asyncio
import os
import uuid
import glob
import atexit
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool


_test_db_counter = 0
_test_db_paths = []


def _cleanup_test_artifacts():
    for db_path in _test_db_paths:
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
        except Exception:
            pass
    
    for pattern in ["test_integration_db_*.sqlite", "test_db_*.sqlite", "test_clear_embeddings_db_*.sqlite"]:
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
        default_strategy = ChunkingStrategy(
            id="default",
            name="Default",
            description="Standard recursive chunking",
            chunk_size=settings.default_chunk_size,
            chunk_overlap=settings.default_chunk_overlap,
            separators=["\n\n", "\n", ". "],
            embedding_model=settings.embedding_model,
            is_system=True,
        )
        session.add(default_strategy)
        
        api_strategy = ChunkingStrategy(
            id="api-docs",
            name="API Documentation",
            description="Specialized chunking for API docs",
            chunk_size=300,
            chunk_overlap=30,
            separators=["\n## ", "\n### ", "\n"],
            embedding_model=settings.embedding_model,
            is_api_aware=True,
            is_system=True,
        )
        session.add(api_strategy)
        await session.commit()
    
    yield
    
    db_session.engine = original_engine
    await new_engine.dispose()
    
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass
