import pytest
import pytest_asyncio
import io
import os
import uuid
import glob
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    for pattern in ["test_db_*.sqlite"]:
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
_test_doc = "AI short.pdf"

@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    global _test_db_counter
    _test_db_counter += 1
    
    test_db_url = f"sqlite+aiosqlite:///./data/test_db_{_test_db_counter}_{uuid.uuid4().hex[:8]}.sqlite"
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


@pytest_asyncio.fixture(scope="function")
async def auth_client(setup_test_db):
    from src.api.main import app
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"pdf_test_{uuid.uuid4().hex[:8]}@example.com"
        await ac.post("/api/v1/auth/signup", json={
            "email": test_email,
            "password": "testpassword123"
        })
        login_response = await ac.post("/api/v1/auth/login", json={
            "email": test_email,
            "password": "testpassword123"
        })
        token = login_response.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


async def upload_and_wait_for_document(client: AsyncClient, filename: str, strategy_id: str = "default") -> str:
    test_file_path = Path(__file__).parent.parent / "docs" / filename
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": (filename, io.BytesIO(content), "application/pdf")}
    data = {"strategy_id": strategy_id}
    
    response = await client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    doc_id = response.json()["id"]
    
    import asyncio
    for _ in range(180):
        await asyncio.sleep(1)
        status_response = await client.get(f"/api/v1/documents/{doc_id}/status")
        if status_response.status_code == 200:
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break
    
    return doc_id


@pytest.mark.asyncio
async def test_upload_test_doc(auth_client):
    test_file_path = Path(__file__).parent.parent / "docs" / _test_doc
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": ("AI short.pdf", io.BytesIO(content), "application/pdf")}
    data = {"strategy_id": "default"}
    
    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    result = response.json()
    
    assert result["title"] == "AI short.pdf"
    assert result["doc_type"] == "pdf"
    assert result["status"] == "pending"
    
    return result["id"]


@pytest.mark.asyncio
async def test_upload_and_process_test_doc(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, _test_doc)
    
    status_response = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
    assert status_response.status_code == 200
    status = status_response.json()
    
    if status["status"] == "processing":
        import asyncio
        for _ in range(60):
            await asyncio.sleep(1)
            status_response = await auth_client.get(f"/api/v1/documents/{doc_id}/status")
            status = status_response.json()
            if status["status"] in ["completed", "failed"]:
                break
    
    assert status["status"] == "completed", f"Document status is {status['status']}: {status.get('error_message', '')}"
    assert status["chunk_count"] > 0
    
    return doc_id, status["chunk_count"]


@pytest.mark.asyncio
async def test_chunks_endpoint_exists(auth_client):
    
    test_file_path = Path(__file__).parent.parent / "docs" / _test_doc
    
    with open(test_file_path, "rb") as f:
        content = f.read()
    
    files = {"file": ("test_chunks.pdf", io.BytesIO(content), "application/pdf")}
    data = {"strategy_id": "default"}
    
    response = await auth_client.post("/api/v1/documents", files=files, data=data)
    assert response.status_code == 201
    doc_id = response.json()["id"]
    
    chunks_response = await auth_client.get(f"/api/v1/documents/{doc_id}/chunks")
    assert chunks_response.status_code == 200


@pytest.mark.asyncio
async def test_chat_with_test_doc(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, _test_doc)
    
    import asyncio
    await asyncio.sleep(2)
    
    response = await auth_client.post("/api/v1/query", json={
        "question": "How to use AI?",
        "document_ids": [doc_id]
    })
    
    assert response.status_code == 200
    result = response.json()
    
    assert "answer" in result
    assert "sources" in result


@pytest.mark.asyncio
async def test_chat_streaming_with_test_doc(auth_client):
    doc_id = await upload_and_wait_for_document(auth_client, _test_doc)
    
    import asyncio
    await asyncio.sleep(2)
    
    tokens = []
    
    async with auth_client.stream("POST", "/api/v1/query/stream", json={
        "question": "What is AI?",
        "document_ids": [doc_id]
    }) as response:
        assert response.status_code == 200
        
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                import json
                data = json.loads(data_str)
                if "token" in data:
                    tokens.append(data["token"])
    
    assert len(tokens) > 0
    full_response = "".join(tokens)
    assert len(full_response) > 0
