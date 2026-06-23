"""FastAPI routes for the API documentation RAG pipeline.

Provides endpoints for ingesting and querying API documentation documents
(DOCX and PDF).  Routes are registered under the ``/query/api-docs`` prefix
and wired into the main app at ``/api/v1``.
"""

from __future__ import annotations

import logging
import os
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.core.config import get_settings
from src.core.security import sanitize_filename
from src.domain.rag.api_docs.manager import get_manager
from src.domain.rag.api_docs.pipeline.schemas import ApiDocQueryRequest
from src.infrastructure.database.models import ChunkingStrategy, Document, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query/api-docs", tags=["API Documentation"])
settings = get_settings()

# Module-level manager singleton
_manager = get_manager()

# -- Magic bytes for file type validation --
_DOCX_MAGIC = b"PK\x03\x04"  # ZIP archive header (DOCX is a ZIP)
_PDF_MAGIC = b"%PDF"


def _validate_file_magic(content: bytes, expected_type: str) -> None:
    """Validate file content matches expected magic bytes.

    Args:
        content: Raw file bytes (at least 4 bytes).
        expected_type: ``"docx"`` or ``"pdf"``.

    Raises:
        HTTPException: If the magic bytes do not match.
    """
    if expected_type == "docx" and not content.startswith(_DOCX_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file: expected a DOCX file (ZIP archive).",
        )
    elif expected_type == "pdf" and not content.startswith(_PDF_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file: expected a PDF file.",
        )


def _is_safe_path(file_path: str, allowed_dir: str) -> bool:
    """Verify that *file_path* is within *allowed_dir* (prevents path traversal)."""
    real_path = os.path.realpath(file_path)
    real_allowed = os.path.realpath(allowed_dir)
    return real_path.startswith(real_allowed + os.sep) or real_path == real_allowed


# ---------------------------------------------------------------------------
# Simple in-memory rate limiter (per-user, per-endpoint)
# ---------------------------------------------------------------------------

import collections
import time as time_module


class _RateLimiter:
    """Sliding-window rate limiter keyed by ``(user_id, endpoint)``."""

    def __init__(self, max_requests: int = 20, window_seconds: int = 60) -> None:
        self._max_requests = max_requests
        self._window = window_seconds
        self._buckets: dict[tuple[str, str], collections.deque] = {}

    def check(self, user_id: str, endpoint: str) -> None:
        """Raise ``HTTPException(429)`` if the user has exceeded the rate limit."""
        now = time_module.time()
        key = (user_id, endpoint)
        if key not in self._buckets:
            self._buckets[key] = collections.deque()

        bucket = self._buckets[key]
        # Purge timestamps outside the window
        while bucket and bucket[0] < now - self._window:
            bucket.popleft()

        if len(bucket) >= self._max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )

        bucket.append(now)


_rate_limiter = _RateLimiter(max_requests=30, window_seconds=60)


# =========================================================================
# Task 8.1 — Query endpoint
# =========================================================================


@router.post("")
async def query_api_docs(
    request: ApiDocQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Query a previously ingested API documentation document.

    If the document has not been indexed yet (e.g. uploaded via the regular
    document upload endpoint), the pipeline is run on-the-fly:  the file is
    extracted, chunked, and indexed before answering the query.
    """
    # Rate-limit check
    _rate_limiter.check(str(current_user.id), "query")

    logger.info(
        "API Doc query - user: %s, doc: %s, query: %r",
        current_user.id,
        request.document_id,
        request.query[:100],
    )
    start_time = time.time()

    try:
        # ------------------------------------------------------------------
        # Step 1: Verify document exists and user has access
        # ------------------------------------------------------------------
        result = await db.execute(
            select(Document).where(
                Document.id == request.document_id,
                Document.user_id == current_user.id,
            )
        )
        document = result.scalar_one_or_none()

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        logger.info(
            "Document found: type=%s, file=%s", document.doc_type, document.file_path
        )

        # ------------------------------------------------------------------
        # Step 2: Index on-the-fly if not already indexed
        # ------------------------------------------------------------------
        if not _manager.is_indexed(request.document_id, str(current_user.id)):
            logger.info("Document not indexed — running pipeline on-the-fly")
            ingest_result = await _run_on_the_fly_ingestion(
                document=document,
                document_id=request.document_id,
                user_id=str(current_user.id),
            )
            logger.info("On-the-fly indexing complete: %s", ingest_result)

        # ------------------------------------------------------------------
        # Step 3: Run retrieval + generation
        # ------------------------------------------------------------------
        response = await _manager.query(
            document_id=request.document_id,
            query_text=request.query,
            top_k=request.top_k,
            user_id=str(current_user.id),
        )

        # Attach total latency
        response.latency_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "API Doc query completed in %.2fs — %d sources, confidence=%.3f",
            time.time() - start_time,
            len(response.sources),
            response.confidence,
        )
        return response.model_dump()

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("API Doc query failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process query. Please try again.",
        )


# =========================================================================
# Task 8.3 & 8.4 — Ingestion endpoint
# =========================================================================


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_api_doc(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Ingest a DOCX or PDF API documentation file.

    The file is:

    1. Validated and saved to ``settings.upload_dir``
    2. A ``Document`` record is created in the database
    3. The full pipeline is executed: extraction → chunking → indexing
    4. The document becomes immediately queryable via ``POST /query/api-docs``

    Supported file types: ``.docx``, ``.pdf``
    """
    # Rate-limit check
    _rate_limiter.check(str(current_user.id), "ingest")

    logger.info("API Doc ingest - user: %s, file: %s", current_user.id, file.filename)

    # Track file path for cleanup on failure
    file_path: str | None = None
    _ingestion_succeeded = False

    try:
        # ------------------------------------------------------------------
        # Stage 1: Validate input
        # ------------------------------------------------------------------
        if file.filename is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must have a filename",
            )

        allowed_extensions = {".docx", ".pdf"}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type '{ext}'. Supported: {', '.join(allowed_extensions)}",
            )

        doc_type = ext.lstrip(".")

        # Validate MIME type from UploadFile if available
        if file.content_type:
            allowed_mimes = {
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
            if file.content_type not in allowed_mimes:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unexpected content type '{file.content_type}' for a {doc_type} file.",
                )

        # ------------------------------------------------------------------
        # Stage 2: Validate file size before reading (DoS protection)
        # ------------------------------------------------------------------
        max_bytes = settings.max_upload_size_mb * 1024 * 1024

        # Use UploadFile.size if available (Starlette/FastAPI populates this)
        if file.size is not None and file.size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {settings.max_upload_size_mb}MB.",
            )

        # Read file content in chunks for memory safety and size validation
        content = await file.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {settings.max_upload_size_mb}MB.",
            )

        # ------------------------------------------------------------------
        # Stage 2b: Validate magic bytes (prevents extension spoofing)
        # ------------------------------------------------------------------
        if len(content) < 4:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File is too small to be a valid document.",
            )
        _validate_file_magic(content, doc_type)

        # ------------------------------------------------------------------
        # Stage 3: Save to disk (path-traversal safe)
        # ------------------------------------------------------------------
        os.makedirs(settings.upload_dir, exist_ok=True)

        # Strip directory components from filename to prevent path traversal
        safe_original = os.path.basename(file.filename)
        safe_filename = sanitize_filename(safe_original)
        unique_filename = f"{uuid.uuid4()}_{safe_filename}"
        file_path = os.path.join(settings.upload_dir, unique_filename)

        # Resolve and verify the final path is within upload_dir
        file_path = os.path.realpath(file_path)
        if not _is_safe_path(file_path, settings.upload_dir):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file path.",
            )

        with open(file_path, "wb") as f:
            f.write(content)
        logger.info("Saved uploaded file to %s (%d bytes)", file_path, len(content))

        # ------------------------------------------------------------------
        # Stage 4: Create Document record in database
        # ------------------------------------------------------------------
        strategy_result = await db.execute(
            select(ChunkingStrategy).where(ChunkingStrategy.id == "recursive")
        )
        strategy = strategy_result.scalar_one_or_none()
        if not strategy:
            strategy = ChunkingStrategy(
                id="recursive",
                name="Recursive",
                description="Recursive chunking for general documents",
                chunk_size=settings.default_chunk_size,
                chunk_overlap=settings.default_chunk_overlap,
                separators=["\n\n", "\n", ". "],
                embedding_model=settings.embedding_model,
                is_system=True,
            )
            db.add(strategy)

        document_id = str(uuid.uuid4())
        document = Document(
            id=document_id,
            user_id=current_user.id,
            title=file.filename,
            doc_type=doc_type,
            file_path=file_path,
            file_size=len(content),
            chunking_strategy_id=strategy.id if strategy else "recursive",
            is_api_doc=True,
            status="indexing",
        )
        db.add(document)
        await db.commit()
        logger.info("Created document record: %s", document_id)

        # ------------------------------------------------------------------
        # Stage 5: Run the extraction → chunking → indexing pipeline
        # ------------------------------------------------------------------
        try:
            if doc_type == "docx":
                ingest_result = await _manager.ingest_docx(
                    file_path, document_id, user_id=str(current_user.id)
                )
            elif doc_type == "pdf":
                ingest_result = await _manager.ingest_pdf(
                    file_path, document_id, user_id=str(current_user.id)
                )
            else:
                # Should not reach here (validated above)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Unsupported document type.",
                )
        except Exception as exc:
            logger.error("Ingestion pipeline failed: %s", exc, exc_info=True)
            document.status = "error"
            document.error_message = str(exc)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Document processing failed. Please try again.",
            )

        # ------------------------------------------------------------------
        # Stage 6: Update document status
        # ------------------------------------------------------------------
        document.status = "indexed"
        document.chunk_count = ingest_result.get("chunk_count", 0)
        document.processing_message = "Successfully indexed for API doc querying"
        await db.commit()

        _ingestion_succeeded = True

        logger.info(
            "Ingestion complete - doc: %s, chunks: %d",
            document_id,
            ingest_result.get("chunk_count", 0),
        )

        return {
            "document_id": document_id,
            "title": file.filename,
            "doc_type": doc_type,
            "status": "indexed",
            "chunk_count": ingest_result.get("chunk_count", 0),
            "interface_count": ingest_result.get("interface_count", 0),
            "enum_count": ingest_result.get("enum_count", 0),
            "message": "Document ingested successfully",
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("API Doc ingestion failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to ingest document. Please try again.",
        )
    finally:
        # Clean up temp file on failure (stages 3+ may have created it)
        if file_path is not None and os.path.exists(file_path) and not _ingestion_succeeded:
            try:
                os.remove(file_path)
                logger.info("Cleaned up file on ingestion failure: %s", file_path)
            except Exception as cleanup_exc:
                logger.warning(
                    "Failed to clean up file %s: %s", file_path, cleanup_exc
                )


# =========================================================================
# Utility endpoints
# =========================================================================


@router.get("/documents", status_code=status.HTTP_200_OK)
async def list_indexed_docs(
    current_user: User = Depends(get_current_user),
) -> dict:
    """List all indexed API documentation document IDs belonging to the current user."""
    docs = _manager.get_indexed_docs(user_id=str(current_user.id))
    logger.info("List indexed docs - user: %s, count: %d", current_user.id, len(docs))
    return {
        "document_ids": docs,
        "count": len(docs),
    }


@router.get("/documents/{document_id}/status", status_code=status.HTTP_200_OK)
async def get_doc_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Check whether a document is indexed and ready for querying."""
    # Verify document in DB and user access
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return {
        "document_id": document_id,
        "title": document.title,
        "doc_type": document.doc_type,
        "indexed": _manager.is_indexed(document_id, user_id=str(current_user.id)),
        "db_status": document.status,
    }


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_indexed_doc(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Remove a document from the in-memory index.

    The database record remains untouched; only the in-memory chunk graph
    and retriever are purged.
    """
    # Verify document in DB and user access
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if _manager.is_indexed(document_id, user_id=str(current_user.id)):
        _manager.remove_document(document_id, user_id=str(current_user.id))
        logger.info("Removed document %s from in-memory index", document_id)

    return None


# =========================================================================
# Task 8.5 — On-the-fly ingestion helper with graceful fallback
# =========================================================================


async def _run_on_the_fly_ingestion(
    document: Document,
    document_id: str,
    user_id: str = "",
) -> dict:
    """Run the appropriate ingestion pipeline based on document type.

    Implements graceful fallback: if DOCX extraction fails, attempts PDF
    fallback extraction on the same file.
    """
    doc_type = document.doc_type

    if doc_type == "docx":
        try:
            return await _manager.ingest_docx(
                document.file_path, document_id, user_id=user_id
            )
        except Exception as exc:
            logger.warning(
                "DOCX ingestion failed for %s, trying PDF fallback: %s",
                document_id,
                exc,
            )
            # Fall through to PDF fallback
            try:
                return await _manager.ingest_pdf(
                    document.file_path, document_id, user_id=user_id
                )
            except Exception as pdf_exc:
                logger.error(
                    "PDF fallback also failed for %s: %s",
                    document_id,
                    pdf_exc,
                    exc_info=True,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to process document.",
                )

    elif doc_type == "pdf":
        try:
            return await _manager.ingest_pdf(
                document.file_path, document_id, user_id=user_id
            )
        except Exception as exc:
            logger.error(
                "PDF ingestion failed for %s: %s",
                document_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to process PDF document.",
            )

    else:
        logger.warning(
            "Unsupported doc_type %s for on-the-fly ingestion", doc_type
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported document type.",
        )
