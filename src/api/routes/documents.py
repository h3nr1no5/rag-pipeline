import collections
import json
import logging
import os
import time as time_module
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...core.security import sanitize_filename
from ...domain.services.progress import compute_stage_progress
from ...infrastructure.database.models import Chunk, ChunkingStrategy, Document, User
from ...infrastructure.database.models import ProcessingConfig as ProcessingConfigModel
from ..dependencies import get_current_user, get_db
from ..schemas import (
    STRATEGY_TYPE_SCHEMAS,
    ChunkingStrategyCreate,
    ChunkingStrategyResponse,
    ChunkingStrategyUpdate,
    ChunkResponse,
    DocumentChunksResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    ProcessingConfigResponse,
    StrategyTypesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Documents"])
settings = get_settings()


def _is_safe_path(file_path: str, allowed_dir: str) -> bool:
    """Verify that *file_path* is within *allowed_dir* (prevents path traversal)."""
    real_path = os.path.realpath(file_path)
    real_allowed = os.path.realpath(allowed_dir)
    return real_path.startswith(real_allowed + os.sep) or real_path == real_allowed


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
        while bucket and bucket[0] < now - self._window:
            bucket.popleft()

        if len(bucket) >= self._max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )

        bucket.append(now)


_upload_rate_limiter = _RateLimiter(max_requests=20, window_seconds=60)


def _get_or_create_default_strategy(db: AsyncSession) -> ChunkingStrategy:
    return ChunkingStrategy(
        id="recursive",
        name="Recursive",
        description="Recursive chunking for general documents",
        chunk_size=settings.default_chunk_size,
        chunk_overlap=settings.default_chunk_overlap,
        separators=["\n\n", "\n", ". "],
        embedding_model=settings.embedding_model,
        engine_type="recursive",
        use_hyperlinks=False,
        is_system=True,
    )


@router.get("/strategies/types", response_model=StrategyTypesResponse)
async def get_strategy_types():
    """Return static schema definitions for all chunking engine types.
    No authentication required — used by the UI to dynamically render config forms."""
    return StrategyTypesResponse(types=STRATEGY_TYPE_SCHEMAS)


@router.post("/strategies", response_model=ChunkingStrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    strategy_data: ChunkingStrategyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    strategy = ChunkingStrategy(
        id=str(uuid.uuid4()),
        name=strategy_data.name,
        description=strategy_data.description,
        chunk_size=strategy_data.chunk_size,
        chunk_overlap=strategy_data.chunk_overlap,
        separators=strategy_data.separators,
        embedding_model=settings.embedding_model,
        use_hyperlinks=strategy_data.use_hyperlinks,
    )
    
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    
    return strategy


@router.get("/strategies", response_model=list[ChunkingStrategyResponse])
async def list_strategies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ChunkingStrategy)
        .where(ChunkingStrategy.id != "default")
        .order_by(ChunkingStrategy.is_system.desc(), ChunkingStrategy.name)
    )
    strategies = result.scalars().all()
    return list(strategies)


@router.get("/strategies/{strategy_id}", response_model=ChunkingStrategyResponse)
async def get_strategy(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(ChunkingStrategy).where(ChunkingStrategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    
    if not strategy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    
    return strategy


@router.patch("/strategies/{strategy_id}", response_model=ChunkingStrategyResponse)
async def update_strategy(
    strategy_id: str,
    update_data: ChunkingStrategyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(ChunkingStrategy).where(ChunkingStrategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    if strategy.is_system:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="System strategies cannot be modified")

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(strategy, key, value)

    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.post("/documents", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    strategy_id: str = Form(default="recursive"),
    chunk_size: Optional[int] = Form(None),
    chunk_overlap: Optional[int] = Form(None),
    separators: Optional[str] = Form(None),
    use_hyperlinks: Optional[bool] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_types = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "text/plain": "txt",
        "text/markdown": "md",
        "application/x-yaml": "yaml",
        "application/yaml": "yaml",
    }
    
    content_type = file.content_type or "application/octet-stream"
    doc_type = allowed_types.get(content_type)
    
    if file.filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must have a filename",
        )
    
    if doc_type is None and not (file.filename.endswith((".yaml", ".yml", ".json"))):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {content_type}",
        )
    
    if file.filename.endswith((".yaml", ".yml")):
        doc_type = "yaml"
    elif file.filename.endswith(".json"):
        doc_type = "json"
    elif doc_type is None:
        doc_type = "txt"
    
    # Rate limiting: prevent abuse
    _upload_rate_limiter.check(str(current_user.id), "upload")

    os.makedirs(settings.upload_dir, exist_ok=True)
    safe_filename = sanitize_filename(file.filename)
    unique_filename = f"{uuid.uuid4()}_{safe_filename}"
    file_path = os.path.join(settings.upload_dir, unique_filename)

    # Defense-in-depth: prevent path traversal
    if not _is_safe_path(file_path, settings.upload_dir):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path.",
        )

    content = await file.read()
    
    MAX_UPLOAD_BYTES = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {settings.max_upload_size_mb}MB",
        )
    
    if doc_type == "pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is not a valid PDF (missing PDF magic bytes)",
        )
    
    with open(file_path, "wb") as f:
        f.write(content)
    
    strategy_result = await db.execute(select(ChunkingStrategy).where(ChunkingStrategy.id == strategy_id))
    strategy = strategy_result.scalar_one_or_none()
    
    if not strategy:
        strategy = _get_or_create_default_strategy(db)
    
    engine_type = getattr(strategy, "engine_type", "recursive")
    if engine_type == "semantic" and doc_type != "pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The Semantic Chunking strategy can only be used with PDF documents",
        )

    if engine_type == "api-docs" and doc_type not in ("docx", "pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API Documentation strategy only supports DOCX and PDF files",
        )
    
    # Parse separators override if provided
    parsed_separators = None
    if separators is not None:
        try:
            parsed_separators = json.loads(separators)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="separators must be a valid JSON array of strings",
            )

        if not isinstance(parsed_separators, list) or not all(isinstance(s, str) for s in parsed_separators) or len(parsed_separators) > 20:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="separators must be a JSON array of strings with at most 20 items",
            )

    if engine_type != "api-docs":
        if chunk_size is not None:
            chunk_size = max(50, min(2000, chunk_size))
        if chunk_overlap is not None:
            chunk_overlap = max(0, min(500, chunk_overlap))

    # Build effective params: override defaults with any provided values
    effective_chunk_size = chunk_size if chunk_size is not None else (strategy.chunk_size if engine_type != "api-docs" else 0)
    effective_chunk_overlap = chunk_overlap if chunk_overlap is not None else (strategy.chunk_overlap if engine_type != "api-docs" else 0)
    effective_separators = parsed_separators if parsed_separators is not None else (strategy.separators if engine_type != "api-docs" else [])
    effective_use_hyperlinks = use_hyperlinks if use_hyperlinks is not None else (strategy.use_hyperlinks if engine_type != "api-docs" else False)
    
    document = Document(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=file.filename,
        doc_type=doc_type,
        file_path=file_path,
        file_size=len(content),
        chunking_strategy_id=strategy.id,
        status="pending",
    )
    
    db.add(document)
    
    # Create a ProcessingConfig record with the effective params
    processing_config = ProcessingConfigModel(
        id=str(uuid.uuid4()),
        document_id=document.id,
        strategy_id=strategy.id,
        chunk_size=effective_chunk_size,
        chunk_overlap=effective_chunk_overlap,
        separators=effective_separators,
        use_hyperlinks=effective_use_hyperlinks,
        engine_type=engine_type,
    )
    db.add(processing_config)
    document.current_processing_config_id = processing_config.id
    
    await db.commit()
    
    document_id = document.id
    document_title = document.title
    document_type = document.doc_type
    
    from ...domain.services.processor import trigger_document_processing
    trigger_document_processing(document_id)
    
    return DocumentUploadResponse(
        id=document_id,
        title=document_title,
        doc_type=document_type,
        status="pending",
        message="Document uploaded. Processing will begin shortly.",
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document, ChunkingStrategy)
        .join(ChunkingStrategy, Document.chunking_strategy_id == ChunkingStrategy.id)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
    )
    rows = result.all()
    
    # Bulk load processing configs for all documents to avoid N+1 queries
    doc_ids = [doc.id for doc, _ in rows]
    config_map = {}
    if doc_ids:
        config_result = await db.execute(
            select(ProcessingConfigModel)
            .where(ProcessingConfigModel.document_id.in_(doc_ids))
            .order_by(ProcessingConfigModel.created_at.desc())
        )
        all_configs = config_result.scalars().all()
        for c in all_configs:
            if c.document_id not in config_map:
                config_map[c.document_id] = c
    
    documents = []
    for doc, strategy in rows:
        progress = compute_stage_progress(
            doc.processing_step,
            doc.saved_chunks or 0,
            doc.chunk_count or 0,
        )
        current_config = config_map.get(doc.id)
        documents.append(DocumentResponse(
            id=doc.id,
            title=doc.title,
            doc_type=doc.doc_type,
            status=doc.status,
            chunk_count=doc.chunk_count,
            file_size=doc.file_size,
            created_at=doc.created_at,
            chunking_strategy=ChunkingStrategyResponse.model_validate(strategy),
            embedded=getattr(doc, 'embedded', False),
            parsing_progress=progress["parsing"],
            chunking_progress=progress["chunking"],
            saving_progress=progress["saving"],
            saved_chunks=doc.saved_chunks or 0,
            processing_config=ProcessingConfigResponse.model_validate(current_config) if current_config else None,
        ))
    
    return DocumentListResponse(documents=documents, total=len(documents))


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document, ChunkingStrategy)
        .join(ChunkingStrategy, Document.chunking_strategy_id == ChunkingStrategy.id)
        .where(Document.id == document_id, Document.user_id == current_user.id)
    )
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    
    doc, strategy = row

    progress = compute_stage_progress(
        doc.processing_step,
        doc.saved_chunks or 0,
        doc.chunk_count or 0,
    )

    # Load processing configs for this document
    configs_result = await db.execute(
        select(ProcessingConfigModel)
        .where(ProcessingConfigModel.document_id == document_id)
        .order_by(ProcessingConfigModel.created_at.desc())
    )
    all_configs = list(configs_result.scalars().all())

    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        doc_type=doc.doc_type,
        status=doc.status,
        chunk_count=doc.chunk_count,
        file_size=doc.file_size,
        created_at=doc.created_at,
        chunking_strategy=ChunkingStrategyResponse.model_validate(strategy),
        embedded=getattr(doc, 'embedded', False),
        parsing_progress=progress["parsing"],
        chunking_progress=progress["chunking"],
        saving_progress=progress["saving"],
        saved_chunks=doc.saved_chunks or 0,
        processing_config=ProcessingConfigResponse.model_validate(all_configs[0]) if all_configs else None,
        processing_configs=[ProcessingConfigResponse.model_validate(c) for c in all_configs],
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    
    from ...infrastructure.database.models import APIEndpoint, Chunk, QueryCache
    
    await db.execute(delete(QueryCache).where(QueryCache.document_id == document_id))
    
    chunk_result = await db.execute(select(Chunk.id).where(Chunk.document_id == document_id))
    chunk_ids = [row[0] for row in chunk_result.fetchall()]
    if chunk_ids:
        await db.execute(delete(APIEndpoint).where(APIEndpoint.chunk_id.in_(chunk_ids)))
    await db.execute(delete(Chunk).where(Chunk.document_id == document_id))
    
    await db.delete(document)
    await db.commit()


@router.post("/documents/{document_id}/clear-embeddings", status_code=status.HTTP_200_OK)
async def clear_document_embeddings(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    
    if document.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot clear embeddings. Document status is '{document.status}', expected 'completed'."
        )
    
    chunks_result = await db.execute(
        select(Chunk).where(Chunk.document_id == document_id)
    )
    chunks = chunks_result.scalars().all()
    chunk_count = len(chunks)
    
    for chunk in chunks:
        chunk.embedding = None
        chunk.embedding_id = None
    
    document.embedded = False
    document.saved_chunks = 0
    document.status = "pending"
    document.processing_step = None
    document.processing_message = "Embeddings cleared. Ready for re-processing."
    
    await db.commit()
    
    return {
        "id": document.id,
        "title": document.title,
        "message": f"Cleared embeddings from {chunk_count} chunks. Document is ready for re-processing.",
        "chunk_count": chunk_count,
    }


@router.post("/documents/{document_id}/reprocess", status_code=status.HTTP_200_OK)
async def reprocess_document(
    document_id: str,
    chunk_size: Optional[int] = Form(None),
    chunk_overlap: Optional[int] = Form(None),
    separators: Optional[str] = Form(None),
    use_hyperlinks: Optional[bool] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    
    # Load strategy (need current defaults)
    strategy_result = await db.execute(
        select(ChunkingStrategy).where(ChunkingStrategy.id == document.chunking_strategy_id)
    )
    strategy = strategy_result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Associated strategy not found")
    
    # Parse separators if provided as JSON string
    parsed_separators = None
    if separators is not None:
        try:
            parsed_separators = json.loads(separators)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid separators JSON")

        if not isinstance(parsed_separators, list) or not all(isinstance(s, str) for s in parsed_separators) or len(parsed_separators) > 20:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="separators must be a JSON array of strings with at most 20 items",
            )

    if chunk_size is not None:
        chunk_size = max(50, min(2000, chunk_size))
    if chunk_overlap is not None:
        chunk_overlap = max(0, min(500, chunk_overlap))

    # Merge overrides with strategy defaults
    effective_chunk_size = chunk_size if chunk_size is not None else strategy.chunk_size
    effective_chunk_overlap = chunk_overlap if chunk_overlap is not None else strategy.chunk_overlap
    effective_separators = parsed_separators if parsed_separators is not None else strategy.separators
    effective_use_hyperlinks = use_hyperlinks if use_hyperlinks is not None else strategy.use_hyperlinks
    
    # Create new ProcessingConfig (old config is retained, not deleted)
    new_config = ProcessingConfigModel(
        id=str(uuid.uuid4()),
        document_id=document_id,
        strategy_id=strategy.id,
        chunk_size=effective_chunk_size,
        chunk_overlap=effective_chunk_overlap,
        separators=effective_separators,
        use_hyperlinks=effective_use_hyperlinks,
        engine_type=getattr(strategy, "engine_type", "recursive"),
    )
    db.add(new_config)
    await db.flush()
    
    document.current_processing_config_id = new_config.id
    document.status = "pending"
    document.processing_step = None
    document.processing_message = "Queued for re-processing..."
    document.saved_chunks = 0
    await db.commit()
    
    from ...domain.services.processor import trigger_document_processing
    trigger_document_processing(document_id)
    
    return {
        "id": document.id,
        "title": document.title,
        "status": "pending",
        "saved_chunks": document.saved_chunks,
        "message": "Document queued for re-processing.",
    }


@router.get("/documents/{document_id}/status")
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    
    progress = compute_stage_progress(
        document.processing_step,
        document.saved_chunks or 0,
        document.chunk_count or 0,
    )

    return {
        "id": document.id,
        "title": document.title,
        "doc_type": document.doc_type,
        "status": document.status,
        "processing_step": document.processing_step,
        "processing_message": document.processing_message,
        "total_chars": document.total_chars,
        "processed_chars": document.processed_chars,
        "chunk_count": document.chunk_count,
        "error_message": document.error_message,
        "strategy_id": document.chunking_strategy_id,
        "parsing_progress": progress["parsing"],
        "chunking_progress": progress["chunking"],
        "saving_progress": progress["saving"],
        "saved_chunks": document.saved_chunks or 0,
        "stage_detail": document.processing_message or "",
    }


@router.get("/documents/{document_id}/chunks", response_model=DocumentChunksResponse)
async def get_document_chunks(
    document_id: str,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    
    chunks_result = await db.execute(
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.chunk_index)
        .offset(skip)
        .limit(limit)
    )
    chunks = chunks_result.scalars().all()
    
    return DocumentChunksResponse(
        document_id=document_id,
        chunks=[
            ChunkResponse(
                id=c.id,
                content=c.content,
                chunk_index=c.chunk_index,
                metadata=c.chunk_metadata,
            )
            for c in chunks
        ],
        total=document.chunk_count,
    )


@router.get("/documents/{document_id}/processing-configs", response_model=list[ProcessingConfigResponse])
async def get_document_processing_configs(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    configs_result = await db.execute(
        select(ProcessingConfigModel)
        .where(ProcessingConfigModel.document_id == document_id)
        .order_by(ProcessingConfigModel.created_at.desc())
    )
    configs = configs_result.scalars().all()
    return [ProcessingConfigResponse.model_validate(c) for c in configs]
