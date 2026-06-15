"""Debug script to trace the exact chunk counts during processing."""

import asyncio
import io
import os
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.api.main import app
from tests.integration.conftest import wait_for_document

import src.domain.services.processor as processor_mod
_original_process = processor_mod.process_document_async

TEST_DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")


async def patched_process_document_async(document_id: str):
    """Wrapper that logs chunking details — uses processor's own session maker."""
    from src.infrastructure.database.models import Document, Chunk
    from sqlalchemy import select

    # Use processor's own async_session_maker (patched by setup_test_db)
    asm = processor_mod.async_session_maker

    print(f"\n=== PATCHED PROCESSOR START: doc_id={document_id} ===")
    print(f"  Using async_session_maker: {asm}")
    
    # Log document state before processing
    async with asm() as s:
        result = await s.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if doc:
            print(f"  Before processing: status={doc.status}, chunk_count={doc.chunk_count}, strategy_id={doc.chunking_strategy_id}")
        else:
            print(f"  Document {document_id} NOT FOUND in processor's DB!")
    
    # Call original
    result = await _original_process(document_id)
    
    # Log document state after processing
    async with asm() as s:
        result = await s.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if doc:
            print(f"  After processing: status={doc.status}, chunk_count={doc.chunk_count}, embedded={doc.embedded}")
        else:
            print(f"  After processing: Document {document_id} NOT FOUND!")
        
        chunk_result = await s.execute(select(Chunk).where(Chunk.document_id == document_id))
        chunks = chunk_result.scalars().all()
        print(f"  Actual chunks in DB: {len(chunks)}")
        for i, c in enumerate(chunks):
            print(f"    Chunk {i}: id={c.id[:8]}..., idx={c.chunk_index}, content_len={len(c.content)}, embedding={'SET' if c.embedding else 'NONE'}")
    
    print(f"=== PATCHED PROCESSOR END ===")
    return result


processor_mod.process_document_async = patched_process_document_async


@pytest.mark.asyncio
async def test_debug_chunk_counts(auth_client):
    """Upload a document and trace chunk counts."""
    filename = "sample_python.txt"
    test_file_path = os.path.join(TEST_DOCS_DIR, filename)
    if os.path.exists(test_file_path):
        with open(test_file_path, "rb") as f:
            content = f.read()
    else:
        content = b"Sample document content for testing."
    
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    response = await auth_client.post("/api/v1/documents", files=files, data={"strategy_id": "default"})
    assert response.status_code == 201
    doc_id = response.json()["id"]
    print(f"\nUploaded doc_id: {doc_id}")
    
    await wait_for_document(auth_client, doc_id)
    
    doc_response = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert doc_response.status_code == 200
    doc_data = doc_response.json()
    print(f"\nDocument API response: chunk_count={doc_data['chunk_count']}, embedded={doc_data['embedded']}")
    
    # Now directly query the DB for chunks using the API (same DB the test uses)
    chunks_response = await auth_client.get(f"/api/v1/documents/{doc_id}/chunks")
    print(f"Chunks API response status: {chunks_response.status_code}")
    if chunks_response.status_code == 200:
        chunks_data = chunks_response.json()
        print(f"Chunks API: total={chunks_data.get('total')}, chunks_count={len(chunks_data.get('chunks', []))}")
    
    # Call clear-embeddings
    clear_response = await auth_client.post(f"/api/v1/documents/{doc_id}/clear-embeddings")
    assert clear_response.status_code == 200
    clear_result = clear_response.json()
    print(f"Clear-embeddings response chunk_count: {clear_result['chunk_count']}")
    
    assert clear_result["chunk_count"] == doc_data["chunk_count"], (
        f"MISMATCH! clear-result.chunk_count ({clear_result['chunk_count']}) "
        f"!= doc.chunk_count ({doc_data['chunk_count']})"
    )
    
    print("TEST PASSED!")
