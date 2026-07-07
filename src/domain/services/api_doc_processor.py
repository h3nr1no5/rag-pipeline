"""API documentation processor — orchestrates the full pipeline for api-docs engine type.

Provides the ``_process_api_doc`` function used by the main document processor
when ``engine_type == "api-docs"``, and helpers for persistence and progress
messages.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.rag.api_docs.types import ProgressReporter

logger = logging.getLogger(__name__)


def get_api_doc_processing_message() -> dict[str, str]:
    """Return stage-to-message mapping for API doc processing progress updates."""
    return {
        "extracting": "Extracting API documentation...",
        "indexing": "Indexing chunks...",
    }


async def _process_api_doc(
    document_id: str, file_path: str, doc_type: str, user_id: str = "",
    progress_callback: ProgressReporter | None = None,
) -> dict:
    """Run the full API documentation ingestion pipeline.

    Args:
        document_id: Unique document identifier.
        file_path: Path to the uploaded file on disk.
        doc_type: ``"docx"`` or ``"pdf"``.
        user_id: The document owner identifier (prevents cross-user data leaks).
        progress_callback: Optional async callback for progress updates.

    Returns:
        The result dict from the manager's ingest method (contains
        ``document_id``, ``chunk_count``, etc.).
    """
    from src.domain.rag.api_docs.manager import get_manager

    manager = get_manager()

    if doc_type == "docx":
        result = await manager.ingest_docx(file_path, document_id, user_id=user_id, progress_callback=progress_callback)  # noqa: E501
    elif doc_type == "pdf":
        result = await manager.ingest_pdf(file_path, document_id, user_id=user_id, progress_callback=progress_callback)  # noqa: E501
    else:
        raise ValueError(f"Unsupported doc_type for API doc processing: {doc_type}")

    return result


async def _persist_api_doc_index(
    document_id: str, user_id: str = "", session: AsyncSession | None = None
) -> None:
    """Persist the in-memory API doc index to the ``ApiDocIndex`` table.

    Args:
        document_id: The document to persist.
        user_id: The document owner identifier (prevents cross-user data leaks).
        session: Optional shared session. If provided, use it with flush() instead
            of opening a new session with commit().
    """
    from sqlalchemy import select

    from src.domain.rag.api_docs.chunking.serializer import serialize_chunk_graph
    from src.domain.rag.api_docs.manager import get_manager
    from src.infrastructure.database import async_session_maker
    from src.infrastructure.database.models import ApiDocIndex, Document

    manager = get_manager()
    info = manager.get_document_info(document_id, user_id=user_id)

    if not info:
        logger.warning(
            "Cannot persist API doc index for %s: not found in manager", document_id
        )
        return

    # Serialize domain data
    def _serialize(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        if isinstance(obj, dict):
            return obj
        return vars(obj)

    domain_data = {
        "interfaces": [_serialize(i) for i in info.get("interfaces", [])],
        "enums": [_serialize(e) for e in info.get("enums", [])],
        "error_codes": [_serialize(e) for e in info.get("error_codes", [])],
    }

    # Serialize chunk graph
    graph_data = serialize_chunk_graph(info["graph"]) if info.get("graph") else {}

    # Persist normalized embeddings for restart-safe semantic search.
    # Vectors are saved pre-normalized (from add_graph), and
    # load_embeddings in ApiEmbeddingIndex includes a second L2
    # normalization that is idempotent on unit vectors.
    embeddings_dict = None
    embedding_dim = None
    retriever = info.get("retriever") if info else None
    if retriever and hasattr(retriever, 'embedding_index'):
        emb_index = retriever.embedding_index
        stored = getattr(emb_index, '_embeddings_dict', None)
        if stored:
            embeddings_dict = stored
            embedding_dim = emb_index._dimension

    if session is not None:
        # Use passed session, flush instead of commit
        existing_result = await session.execute(
            select(ApiDocIndex).where(ApiDocIndex.document_id == document_id)
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.domain_data = domain_data
            existing.graph_data = graph_data
            existing.embeddings = embeddings_dict
            existing.embedding_dim = embedding_dim
        else:
            # Verify Document exists
            doc_result = await session.execute(
                select(Document).where(Document.id == document_id)
            )
            doc = doc_result.scalar_one_or_none()
            if not doc:
                logger.warning(
                    "Cannot persist API doc index for %s: Document not found",
                    document_id,
                )
                return

            api_doc_index = ApiDocIndex(
                document_id=document_id,
                domain_data=domain_data,
                graph_data=graph_data,
                embeddings=embeddings_dict,
                embedding_dim=embedding_dim,
            )
            session.add(api_doc_index)

        await session.flush()
    else:
        async with async_session_maker() as own_session:
            # Check for existing row
            existing_result = await own_session.execute(
                select(ApiDocIndex).where(ApiDocIndex.document_id == document_id)
            )
            existing = existing_result.scalar_one_or_none()

            if existing:
                existing.domain_data = domain_data
                existing.graph_data = graph_data
                existing.embeddings = embeddings_dict
                existing.embedding_dim = embedding_dim
            else:
                # Verify Document exists
                doc_result = await own_session.execute(
                    select(Document).where(Document.id == document_id)
                )
                doc = doc_result.scalar_one_or_none()
                if not doc:
                    logger.warning(
                        "Cannot persist API doc index for %s: Document not found",
                        document_id,
                    )
                    return

                api_doc_index = ApiDocIndex(
                    document_id=document_id,
                    domain_data=domain_data,
                    graph_data=graph_data,
                    embeddings=embeddings_dict,
                    embedding_dim=embedding_dim,
                )
                own_session.add(api_doc_index)

            await own_session.commit()
            logger.debug("Persisted API doc index for %s", document_id)
