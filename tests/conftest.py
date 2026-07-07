import asyncio
import atexit
import gc
import glob
import os
import uuid

import pytest
import pytest_asyncio
from dotenv import dotenv_values
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
    """Clean up all test database files and their associated WAL/SHM journals."""
    for db_path in _test_db_paths:
        _remove_sqlite_file(db_path)

    for pattern in ["test_integration_db_*.sqlite", "test_db_*.sqlite", "test_clear_embeddings_db_*.sqlite", "test_chat_db_*.sqlite", "test_chat_e2e_db_*.sqlite", "test_llm_db_*.sqlite"]:  # noqa: E501
        for f in glob.glob(f"./data/{pattern}"):
            _remove_sqlite_file(f)

    uploads_dir = "./data/uploads"
    if os.path.exists(uploads_dir):
        for f in os.listdir(uploads_dir):
            fpath = os.path.join(uploads_dir, f)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except Exception:
                pass


def _remove_sqlite_file(db_path: str) -> None:
    """Remove a SQLite database file along with any associated WAL/SHM journal files."""
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
    except Exception:
        pass
    # Remove associated WAL and SHM journal files that SQLite may leave behind
    for suffix in ("-wal", "-shm"):
        journal_path = db_path + suffix
        try:
            if os.path.exists(journal_path):
                os.remove(journal_path)
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

    import src.infrastructure.database as db_pkg
    db_pkg.async_session_maker = new_session_maker

    from src.domain.services import processor
    processor.async_session_maker = new_session_maker

    # Patch modules that imported async_session_maker at module level before
    # setup_test_db had a chance to replace it (import timing — the test
    # module already imported src.api.main which cascaded to _executor.py).
    import src.api.routes.query._executor as executor
    original_executor_session_maker = executor.async_session_maker
    executor.async_session_maker = new_session_maker

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

    # ── Teardown ──────────────────────────────────────────────────────────────
    # Wait a moment for any lingering background operations to settle before
    # disposing the engine.  This mitigates races where a cancelled document-
    # processing task is still flushing its final DB write.
    await asyncio.sleep(0.1)

    # Restore original engine/session references
    db_session.engine = original_engine

    from src.infrastructure.database import session as session_module
    session_module.async_session_maker = original_session_maker

    from src.domain.services import processor
    processor.async_session_maker = original_session_maker

    db_session.async_session_maker = original_session_maker

    import src.api.routes.query._executor as executor
    executor.async_session_maker = original_executor_session_maker

    # Forcefully close the engine and all its connections
    await new_engine.dispose()

    # Release any Python-level references keeping aiosqlite worker alive
    gc.collect()

    # Retry file removal with backoff (macOS fcntl lock may lag behind dispose())
    for attempt in range(10):
        try:
            _remove_sqlite_file(db_path)
            break
        except PermissionError:
            if attempt == 9:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))


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
    """Cancel and await any pending background tasks.

    This fixture runs its teardown BEFORE ``setup_test_db`` (because it is
    defined *after* it in the file).  This ordering ensures that background
    document-processing and async-query tasks are cancelled and their
    database operations complete before the per-test engine is disposed.
    """
    yield

    # Give tasks a moment to settle
    await asyncio.sleep(0.2)

    # Cancel document-processing tasks
    pending_doc = [t for t in asyncio.all_tasks()
                   if not t.done()
                   and t is not asyncio.current_task()
                   and t.get_name().startswith("process_doc_")]

    if pending_doc:
        for t in pending_doc:
            t.cancel()
        _done, not_done = await asyncio.wait(pending_doc, timeout=15.0)
        for t in not_done:
            try:
                await asyncio.wait_for(t, timeout=2.0)
            except (asyncio.CancelledError, Exception):
                pass

    # Cancel async-query background tasks (named "async_query_*")
    pending_query = [t for t in asyncio.all_tasks()
                     if not t.done()
                     and t is not asyncio.current_task()
                     and t.get_name().startswith("async_query_")]

    if pending_query:
        for t in pending_query:
            t.cancel()
        _done, not_done = await asyncio.wait(pending_query, timeout=15.0)
        for t in not_done:
            try:
                await asyncio.wait_for(t, timeout=2.0)
            except (asyncio.CancelledError, Exception):
                pass


@pytest.fixture(autouse=True)
def collect_garbage():
    """Run garbage collection after every test to prevent tensor/object accumulation.

    This provides a safety net against memory leaks (e.g., MPNet tensor references
    from sentence-transformers) that can cause segfaults in C extension code when
    many tests run in sequence.
    """
    yield
    gc.collect()
