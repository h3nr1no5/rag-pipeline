"""Debug script: trace why clear-embeddings chunk_count differs from Document.chunk_count."""
import asyncio
import io
import uuid
import os
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from httpx import AsyncClient, ASGITransport

import pytest
import pytest_asyncio

from src.api.main import app
from tests.integration.conftest import wait_for_document

TEST_DOCS_DIR = Path(__file__).parent / "docs"


def _read_file(filename: str) -> bytes:
    test_file_path = TEST_DOCS_DIR / filename
    if test_file_path.exists():
        with open(test_file_path, "rb") as f:
            content = f.read()
        print(f"[DEBUG] Read {len(content)} bytes from {test_file_path}")
    else:
        content = b"Sample document content for testing."
        print(f"[DEBUG] File {test_file_path} not found, using fallback ({len(content)} bytes)")
    return content


@pytest.mark.asyncio
async def test_debug_clear_embeddings(setup_test_db):
    # 1. Create auth'd client (same pattern as auth_client fixture)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        test_email = f"debug_{uuid.uuid4().hex[:8]}@example.com"
        await ac.post(
            "/api/v1/auth/signup",
            json={"email": test_email, "password": "testpassword123"},
        )
        login_response = await ac.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": "testpassword123"},
        )
        token = login_response.json()["access_token"]
        ac.headers["Authorization"] = f"Bearer {token}"

        # 2. Upload sample_python.txt
        print("\n=== STEP 1: Upload document ===")
        filename = "sample_python.txt"
        content = _read_file(filename)
        files = {"file": (filename, io.BytesIO(content), "text/plain")}
        response = await ac.post("/api/v1/documents", files=files, data={"strategy_id": "default"})
        assert response.status_code == 201
        doc_id = response.json()["id"]
        print(f"Uploaded document id={doc_id}")

        # 3. Wait for completion
        print("\n=== STEP 2: Wait for processing to complete ===")
        await wait_for_document(ac, doc_id)
        print("Document status: completed")

        # 4. Get document and print chunk_count
        print("\n=== STEP 3: GET document ===")
        doc_response = await ac.get(f"/api/v1/documents/{doc_id}")
        doc_data = doc_response.json()
        print(f"Document chunk_count (from Document model): {doc_data['chunk_count']}")
        print(f"Document embedded: {doc_data['embedded']}")
        print(f"Document status: {doc_data['status']}")

        # 5. Query Chunks table directly — MUST import from session module, NOT from
        #    src.infrastructure.database, because setup_test_db patches
        #    session.async_session_maker but src.infrastructure.database.async_session_maker
        #    is a stale copy (imported by name, not live reference).
        print("\n=== STEP 4: Query Chunks table directly ===")
        from src.infrastructure.database.session import async_session_maker as db_session_maker

        async with db_session_maker() as session:
            from src.infrastructure.database.models import Chunk

            result = await session.execute(
                select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
            )
            all_chunks = result.scalars().all()
            print(f"Actual Chunk records in DB: {len(all_chunks)}")
            for c in all_chunks:
                has_embedding = c.embedding is not None
                content_preview = c.content[:80].replace("\n", "\\n")
                print(f"  Chunk idx={c.chunk_index} id={c.id[:8]}... "
                      f"has_embedding={has_embedding} content='{content_preview}...'")

        # 6. Get chunks via API
        print("\n=== STEP 5: GET chunks via API ===")
        chunks_response = await ac.get(f"/api/v1/documents/{doc_id}/chunks")
        chunks_data = chunks_response.json()
        print(f"Chunks API total (from Document.chunk_count): {chunks_data['total']}")
        print(f"Chunks API actual chunks returned: {len(chunks_data['chunks'])}")

        # 7. Call clear-embeddings
        print("\n=== STEP 6: Call clear-embeddings ===")
        clear_response = await ac.post(f"/api/v1/documents/{doc_id}/clear-embeddings")
        clear_result = clear_response.json()
        print(f"Clear-embeddings response: {clear_result}")
        print(f"clear_result['chunk_count']: {clear_result['chunk_count']}")
        print(f"Document chunk_count (from model): {doc_data['chunk_count']}")
        if clear_result["chunk_count"] != doc_data["chunk_count"]:
            print(f"*** MISMATCH: clear says {clear_result['chunk_count']} but model says {doc_data['chunk_count']} ***")

        # 8. Query Chunks table AFTER clear
        print("\n=== STEP 7: Query Chunks table AFTER clear ===")
        async with db_session_maker() as session:
            from src.infrastructure.database.models import Chunk

            result = await session.execute(
                select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index)
            )
            all_chunks_after = result.scalars().all()
            print(f"Actual Chunk records in DB after clear: {len(all_chunks_after)}")
            for c in all_chunks_after:
                has_embedding = c.embedding is not None
                has_embedding_id = c.embedding_id is not None
                content_preview = c.content[:80].replace("\n", "\\n")
                print(f"  Chunk idx={c.chunk_index} id={c.id[:8]}... "
                      f"embedding={has_embedding} embedding_id={has_embedding_id} "
                      f"content='{content_preview}...'")

        # 9. GET document after clear
        print("\n=== STEP 8: GET document after clear ===")
        doc_after = await ac.get(f"/api/v1/documents/{doc_id}")
        doc_after_data = doc_after.json()
        print(f"Document after clear - chunk_count: {doc_after_data['chunk_count']}")
        print(f"Document after clear - embedded: {doc_after_data['embedded']}")
        print(f"Document after clear - status: {doc_after_data['status']}")
