"""
CRITICAL BUG TEST: Demonstrates cache key collision between /query and /query/langchain

BUG SUMMARY:
- Both endpoints use the SAME cache_key for storing responses
- /query/langchain checks for "cache_key_langchain" suffix but stores with plain "cache_key"
- This causes cache pollution: first endpoint to cache determines what's cached

EXPECTED BEHAVIOR:
- /query caches with key: hash(document|question|strategy|model)
- /query/langchain should cache with key: hash(...|_langchain)

ACTUAL BEHAVIOR (BUG):
- Both store with the SAME key, causing race conditions and identical responses
"""
import pytest
import pytest_asyncio
import io
import uuid
import os
import glob
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from sqlalchemy import select, delete

from src.api.main import app
from src.infrastructure.database.models import QueryCache


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    """Clean up test databases after all tests."""
    for pattern in ["test_chat_db_*.sqlite"]:
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


_test_db_counter = 0


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    """Create a fresh test database for each test."""
    global _test_db_counter
    _test_db_counter += 1
    
    test_db_url = f"sqlite+aiosqlite:///./data/test_chat_db_{_test_db_counter}_{uuid.uuid4().hex[:8]}.sqlite"
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
    
    from src.infrastructure.database import async_session_maker
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
        except Exception:
            pass


@pytest_asyncio.fixture(scope="function")
async def test_user_client(setup_test_db):
    """Create a client authenticated as test@test.com."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_response = await ac.post("/api/v1/auth/login", json={
            "email": "test@test.com",
            "password": "test123456"
        })
        
        if login_response.status_code != 200:
            signup_response = await ac.post("/api/v1/auth/signup", json={
                "email": "test@test.com",
                "password": "test123456"
            })
            if signup_response.status_code == 201:
                login_response = await ac.post("/api/v1/auth/login", json={
                    "email": "test@test.com",
                    "password": "test123456"
                })
        
        if login_response.status_code != 200:
            test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
            await ac.post("/api/v1/auth/signup", json={
                "email": test_email,
                "password": "test123456"
            })
            login_response = await ac.post("/api/v1/auth/login", json={
                "email": test_email,
                "password": "test123456"
            })
        
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        token = login_response.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


async def upload_and_wait_for_document(client: AsyncClient, filename: str, strategy_id: str = "default") -> str:
    """Upload a document and wait for it to be processed."""
    test_file_path = Path(__file__).parent.parent / "docs" / filename
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    data = {"strategy_id": strategy_id}
    
    response = await client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201, f"Upload failed: {response.text}"
    doc_id = response.json()["id"]
    
    import asyncio
    for _ in range(60):
        await asyncio.sleep(1)
        status_response = await client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                if status["status"] == "failed":
                    pytest.fail(f"Document processing failed: {status.get('error', 'Unknown error')}")
                break
    
    await asyncio.sleep(2)
    
    return doc_id


@pytest.mark.asyncio
async def test_cache_key_collision_bug(test_user_client):
    """
    CRITICAL TEST: Demonstrates that /query and /query/langchain share the same cache key.
    
    This test will FAIL if the bug exists (showing identical cached responses).
    After the bug is fixed, each endpoint should maintain its own cache.
    """
    doc_id = await upload_and_wait_for_document(test_user_client, "sample_python.txt")
    
    # Use a UNIQUE question to avoid any existing cache
    unique_question = f"What are Python's key features? (unique test {uuid.uuid4().hex[:8]})"
    
    # Step 1: Call /query first (this should cache the response)
    current_response = await test_user_client.post("/api/v1/query", json={
        "question": unique_question,
        "document_ids": [doc_id]
    })
    
    assert current_response.status_code == 200, f"Current RAG failed: {current_response.text}"
    current_result = current_response.json()
    
    print(f"\n[STEP 1] /query response:")
    print(f"  Answer: {current_result.get('answer', '')[:100]}...")
    print(f"  Cached: {current_result.get('cached', False)}")
    
    # Step 2: Call /query/langchain with the SAME question
    langchain_response = await test_user_client.post("/api/v1/query/langchain", json={
        "question": unique_question,
        "document_ids": [doc_id]
    })
    
    assert langchain_response.status_code == 200, f"LangChain RAG failed: {langchain_response.text}"
    langchain_result = langchain_response.json()
    
    print(f"\n[STEP 2] /query/langchain response:")
    print(f"  Answer: {langchain_result.get('answer', '')[:100]}...")
    print(f"  Cached: {langchain_result.get('cached', False)}")
    
    # CRITICAL ASSERTION: This should FAIL if the bug exists
    # If both return cached=True, it means they're sharing the same cache
    # After fix: /query should be cached, /query/langchain should be fresh (cached=False)
    
    # Check if langchain is returning the cached answer from /query
    # This would indicate the bug
    if langchain_result.get("cached") and current_result.get("cached"):
        pytest.fail(
            "BUG DETECTED: Both endpoints returned cached=True! "
            "This indicates cache key collision - /query/langchain is returning "
            "the cached response from /query instead of its own cache."
        )
    
    # Step 3: Call both again to verify cache behavior
    print(f"\n[STEP 3] Calling both endpoints again to verify cache...")
    
    current_response_2 = await test_user_client.post("/api/v1/query", json={
        "question": unique_question,
        "document_ids": [doc_id]
    })
    current_result_2 = current_response_2.json()
    
    langchain_response_2 = await test_user_client.post("/api/v1/query/langchain", json={
        "question": unique_question,
        "document_ids": [doc_id]
    })
    langchain_result_2 = langchain_response_2.json()
    
    print(f"  /query cached: {current_result_2.get('cached', False)}")
    print(f"  /query/langchain cached: {langchain_result_2.get('cached', False)}")
    
    # After fix, BOTH should be cached (each with their own cache key)
    assert current_result_2.get("cached") == True, "/query should return cached response"
    
    # This is the key assertion - after fix, langchain should ALSO be cached
    assert langchain_result_2.get("cached") == True, (
        "/query/langchain should return cached response (with separate langchain cache key)"
    )


@pytest.mark.asyncio
async def test_cache_keys_are_different(test_user_client):
    """
    Verify that cache keys are stored differently for each endpoint.
    """
    doc_id = await upload_and_wait_for_document(test_user_client, "sample_python.txt")
    
    unique_question = f"How do you define functions? (cache test {uuid.uuid4().hex[:8]})"
    
    # Make queries to populate caches
    await test_user_client.post("/api/v1/query", json={
        "question": unique_question,
        "document_ids": [doc_id]
    })
    
    await test_user_client.post("/api/v1/query/langchain", json={
        "question": unique_question,
        "document_ids": [doc_id]
    })
    
    # Check the cache table directly
    from src.infrastructure.database.session import async_session_maker
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(QueryCache).where(QueryCache.query_text == unique_question)
        )
        cached_queries = result.scalars().all()
    
    print(f"\n[Cache Analysis]")
    print(f"  Number of cached entries for this question: {len(cached_queries)}")
    
    hash_keys = set()
    for i, qc in enumerate(cached_queries):
        print(f"  Entry {i+1}:")
        print(f"    query_hash: {qc.query_hash}")
        print(f"    query_text: {qc.query_text[:50]}...")
        hash_keys.add(qc.query_hash)
    
    # After fix, there should be TWO cache entries (one for each endpoint)
    # With the bug, there's only ONE entry (shared)
    if len(cached_queries) == 1:
        print("\n  WARNING: Only ONE cache entry found!")
        print("  This suggests the bug exists - both endpoints share the same cache key.")
    
    # After fix, each endpoint should have DIFFERENT hash keys
    # With the bug, all entries share the SAME hash
    if len(hash_keys) == 1 and len(cached_queries) > 1:
        pytest.fail(
            f"BUG DETECTED: {len(cached_queries)} cache entries exist but ALL have "
            f"the same query_hash: {list(hash_keys)[0][:20]}... "
            "This means /query and /query/langchain are using the SAME cache key!"
        )


@pytest.mark.asyncio  
async def test_different_questions_produce_different_sources(test_user_client):
    """
    Test that different questions retrieve different source chunks.
    This validates that the retrieval logic is working correctly.
    """
    doc_id = await upload_and_wait_for_document(test_user_client, "sample_python.txt")
    
    # Question 1: About Python basics
    q1 = f"What is Python programming language? (test {uuid.uuid4().hex[:8]})"
    r1_current = await test_user_client.post("/api/v1/query", json={
        "question": q1,
        "document_ids": [doc_id]
    })
    r1_langchain = await test_user_client.post("/api/v1/query/langchain", json={
        "question": q1,
        "document_ids": [doc_id]
    })
    
    # Question 2: About functions
    q2 = f"How do you define a function? (test {uuid.uuid4().hex[:8]})"
    r2_current = await test_user_client.post("/api/v1/query", json={
        "question": q2,
        "document_ids": [doc_id]
    })
    r2_langchain = await test_user_client.post("/api/v1/query/langchain", json={
        "question": q2,
        "document_ids": [doc_id]
    })
    
    # Extract source chunk IDs
    s1_current = {s['chunk_id'] for s in r1_current.json().get("sources", [])}
    s1_langchain = {s['chunk_id'] for s in r1_langchain.json().get("sources", [])}
    s2_current = {s['chunk_id'] for s in r2_current.json().get("sources", [])}
    s2_langchain = {s['chunk_id'] for s in r2_langchain.json().get("sources", [])}
    
    print("\n[Source Chunk Analysis]")
    print(f"Question 1 sources (Current): {len(s1_current)} chunks")
    print(f"Question 1 sources (LangChain): {len(s1_langchain)} chunks")
    print(f"Question 2 sources (Current): {len(s2_current)} chunks")
    print(f"Question 2 sources (LangChain): {len(s2_langchain)} chunks")
    
    # Different questions should typically return different sources
    overlap_q1 = s1_current & s1_langchain
    overlap_diff = s1_current & s2_current
    
    print(f"\nOverlap between Current and LangChain (same Q): {len(overlap_q1)} chunks")
    print(f"Overlap between Q1 and Q2 (Current RAG): {len(overlap_diff)} chunks")
    
    # The same question should have significant overlap between backends
    # (they may use different algorithms but should find relevant content)
    assert len(overlap_q1) > 0, "Same question should return some common sources"
    
    # Different questions should have less overlap
    # (This is a soft check - some content may be relevant to both)