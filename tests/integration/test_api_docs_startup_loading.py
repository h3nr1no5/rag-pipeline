"""Integration test for startup database loading on the API doc pipeline.

Task 3.3 — Verifies that :meth:`ApiDocPipelineManager.load_all_from_db`
correctly restores an in-memory index from persisted ``ApiDocIndex`` rows
without requiring re-ingestion.

The test:
1. Creates a User, Document, and ApiDocIndex row in the test database.
2. Calls ``load_all_from_db()`` on the singleton manager.
3. Verifies the document is marked as indexed.
"""

import uuid

import pytest
from sqlalchemy import select

from src.domain.rag.api_docs.chunking.builder import ChunkGraphBuilder
from src.domain.rag.api_docs.chunking.serializer import serialize_chunk_graph
from src.domain.rag.api_docs.manager import get_manager
from src.domain.rag.api_docs.model.models import (
    APIFunction,
    APIInterface,
    APIParameter,
    APIProperty,
)
from src.infrastructure.database import session as db_session
from src.infrastructure.database.models import ApiDocIndex, ChunkingStrategy, Document, User


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_load_from_db() -> None:
    """load_all_from_db restores an index from an ApiDocIndex row."""
    manager = get_manager()

    # --- Arrange: seed the database with a document + api_doc_index row ---

    # Build a sample chunk graph (same pattern as _make_sample_graph)
    builder = ChunkGraphBuilder()
    iface = APIInterface(
        name="INode",
        description="Node interface",
        methods=[
            APIFunction(
                name="Create",
                return_type="INode",
                parameters=[
                    APIParameter(name="parent", type_annotation="INode"),
                ],
            ),
        ],
        properties=[APIProperty(name="Name", type_annotation="string")],
    )
    graph = builder.build(interfaces=[iface], source_doc="test-doc")
    graph_data = serialize_chunk_graph(graph)

    domain_data = {
        "interfaces": [iface.model_dump()],
        "enums": [],
        "error_codes": [],
    }

    user_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())

    async with db_session.async_session_maker() as session:
        # --- User ---
        session.add(
            User(
                id=user_id,
                email=f"{user_id[:8]}@example.com",
                password_hash="fakehash",
            )
        )

        # --- Chunking strategy (seeded by setup_test_db) ---
        result = await session.execute(
            select(ChunkingStrategy).where(ChunkingStrategy.id == "recursive")
        )
        strategy = result.scalar_one()

        # --- Document ---
        session.add(
            Document(
                id=doc_id,
                user_id=user_id,
                title="Test Doc",
                doc_type="docx",
                file_path="/tmp/test.docx",
                chunking_strategy_id=strategy.id,
            )
        )

        # --- ApiDocIndex ---
        session.add(
            ApiDocIndex(
                document_id=doc_id,
                domain_data=domain_data,
                graph_data=graph_data,
                embeddings=None,
                embedding_dim=None,
            )
        )
        await session.commit()

    # --- Act: load from database ---
    async with db_session.async_session_maker() as session:
        await manager.load_all_from_db(session)

    # --- Assert: document is indexed without re-ingestion ---
    assert manager.is_indexed(doc_id, user_id), (
        f"Document {doc_id} should be indexed after load_all_from_db"
    )
