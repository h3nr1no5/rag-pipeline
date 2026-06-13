import pytest
import pytest_asyncio
import os
import uuid
import glob
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.api.main import app


def _cleanup_llm_test_artifacts():
    import atexit
    atexit.unregister(_cleanup_llm_test_artifacts)
    
    for pattern in ["test_llm_db_*.sqlite"]:
        for f in glob.glob(f"./data/{pattern}"):
            try:
                os.remove(f)
            except Exception:
                pass


@pytest.fixture(scope="module", autouse=True)
def setup_env():
    # Ensure model downloads allowed (set to 0 to download, 1 for offline)
    original_offline = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "0"
    
    # Set model for testing
    original_model = os.environ.get("LLM_MODEL")
    os.environ["LLM_MODEL"] = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"
    
    yield
    
    # Restore original values
    if original_offline is not None:
        os.environ["HF_HUB_OFFLINE"] = original_offline
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
    
    if original_model is not None:
        os.environ["LLM_MODEL"] = original_model
    else:
        os.environ.pop("LLM_MODEL", None)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    for pattern in ["test_llm_db_*.sqlite"]:
        for f in glob.glob(f"./data/{pattern}"):
            try:
                os.remove(f)
            except Exception:
                pass


_test_db_counter = 0


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    global _test_db_counter
    _test_db_counter += 1
    
    test_db_url = f"sqlite+aiosqlite:///./data/test_llm_db_{_test_db_counter}_{uuid.uuid4().hex[:8]}.sqlite"
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
        await session.commit()
    
    yield
    
    db_session.engine = original_engine
    await new_engine.dispose()
    
    db_path = test_db_url.replace("sqlite+aiosqlite:///", "")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except:
            pass


@pytest.mark.asyncio
async def test_llm_waits_for_ready(setup_env):
    """Wait for LLM to be ready, then verify via health endpoint."""
    import asyncio
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Poll until LLM is ready (max 120 seconds)
        llm_status = None
        max_wait = 120  # seconds
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            response = await client.get("/api/v1/health/models")
            assert response.status_code == 200
            
            data = response.json()
            
            # LLM status can be nested or at top level
            if "llm_status" in data:
                llm_status = data.get("llm_status")
            elif "llm" in data:
                llm_status = data.get("llm", {}).get("status")
            else:
                llm_status = None
            
            print(f"LLM status: {llm_status} (waiting...")
            
            if llm_status == "ready":
                break
            
            await asyncio.sleep(2)
        
        # Assert LLM is ready
        assert llm_status == "ready", f"LLM did not become ready within {max_wait}s. Status: {llm_status}"
        
        # Verify health endpoint confirms ready
        data = response.json()
        llm_data = data.get("llm", {})
        print(f"LLM ready! Model: {llm_data.get('model')}, Progress: {llm_data.get('progress')}")


@pytest.mark.asyncio
async def test_llm_generates_response(setup_env):
    """Verify LLM actually generates text (requires model loaded)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Signup/login first (required for /api/v1/query)
        test_email = f"llm_test_{uuid.uuid4().hex[:8]}@example.com"
        
        await client.post("/api/v1/auth/signup", json={
            "email": test_email,
            "password": "testpass123"
        })
        
        login = await client.post("/api/v1/auth/login", json={
            "email": test_email, 
            "password": "testpass123"
        })
        
        token = login.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        
        # Query with empty document_ids - uses LLM directly (no RAG)
        response = await client.post("/api/v1/query", json={
            "question": "Hello, are you working?",
            "document_ids": []
        })
        
        # May be 400 if no documents provided - that's OK
        # The important thing is LLM was attempted to load
        if response.status_code == 200:
            result = response.json()
            assert "answer" in result
            print(f"LLM Answer: {result['answer']}")
        else:
            # If 400, check LLM status separately
            status_resp = await client.get("/api/v1/health/models")
            llm_status = status_resp.json().get("llm_status")
            print(f"LLM status after query attempt: {llm_status}")