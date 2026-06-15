import uuid
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from ..schemas import (
    ChunkingStrategyCreate,
    ChunkingStrategyResponse,
    DocumentUploadResponse,
    DocumentResponse,
    DocumentListResponse,
    ChunkResponse,
    DocumentChunksResponse,
)
from ..dependencies import get_db, get_current_user
from ...infrastructure.database.models import User, Document, Chunk, ChunkingStrategy
from ...core.config import get_settings
from ...core.security import sanitize_filename
from ...domain.services.progress import compute_stage_progress

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Documents"])
settings = get_settings()


def _get_or_create_default_strategy(db: AsyncSession) -> ChunkingStrategy:
    return ChunkingStrategy(
        id="default",
        name="Default",
        chunk_size=settings.default_chunk_size,
        chunk_overlap=settings.default_chunk_overlap,
        separators=["\n\n", "\n", ". "],
        embedding_model=settings.embedding_model,
        is_system=True,
    )


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
        select(ChunkingStrategy).order_by(ChunkingStrategy.is_system.desc(), ChunkingStrategy.name)
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


@router.post("/documents", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    strategy_id: str = Form(default="default"),
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
    
    os.makedirs(settings.upload_dir, exist_ok=True)
    safe_filename = sanitize_filename(file.filename)
    unique_filename = f"{uuid.uuid4()}_{safe_filename}"
    file_path = os.path.join(settings.upload_dir, unique_filename)
    
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
    
    is_api_doc = doc_type in ("yaml", "json")
    
    document = Document(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=file.filename,
        doc_type=doc_type,
        file_path=file_path,
        file_size=len(content),
        chunking_strategy_id=strategy.id,
        is_api_doc=is_api_doc,
        status="pending",
    )
    
    db.add(document)
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
    
    documents = []
    for doc, strategy in rows:
        progress = compute_stage_progress(
            doc.processing_step,
            doc.saved_chunks or 0,
            doc.chunk_count or 0,
        )
        documents.append(DocumentResponse(
            id=doc.id,
            title=doc.title,
            doc_type=doc.doc_type,
            status=doc.status,
            is_api_doc=doc.is_api_doc,
            chunk_count=doc.chunk_count,
            file_size=doc.file_size,
            created_at=doc.created_at,
            chunking_strategy=ChunkingStrategyResponse.model_validate(strategy),
            embedded=getattr(doc, 'embedded', False),
            parsing_progress=progress["parsing"],
            chunking_progress=progress["chunking"],
            saving_progress=progress["saving"],
            saved_chunks=doc.saved_chunks or 0,
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

    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        doc_type=doc.doc_type,
        status=doc.status,
        is_api_doc=doc.is_api_doc,
        chunk_count=doc.chunk_count,
        file_size=doc.file_size,
        created_at=doc.created_at,
        chunking_strategy=ChunkingStrategyResponse.model_validate(strategy),
        embedded=getattr(doc, 'embedded', False),
        parsing_progress=progress["parsing"],
        chunking_progress=progress["chunking"],
        saving_progress=progress["saving"],
        saved_chunks=doc.saved_chunks or 0,
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
    
    from ...infrastructure.database.models import Chunk, QueryCache, APIEndpoint
    
    await db.execute(delete(QueryCache).where(QueryCache.document_id == document_id))
    
    chunk_result = await db.execute(select(Chunk.id).where(Chunk.document_id == document_id))
    chunk_ids = [row[0] for row in chunk_result.fetchall()]
    if chunk_ids:
        await db.execute(delete(APIEndpoint).where(APIEndpoint.chunk_id.in_(chunk_ids)))
    await db.execute(delete(Chunk).where(Chunk.document_id == document_id))
    
    # Delete from Chroma vector index FIRST (before SQLite commit)
    from ...domain.services.llama_index_service import get_llama_index_service
    try:
        li_service = await get_llama_index_service()
        await li_service.delete_document(document_id)
    except Exception:
        logger.warning(
            "Chroma deletion failed for document %s (continuing with SQLite deletion)",
            document_id,
        )

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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    
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
