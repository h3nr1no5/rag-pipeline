import asyncio
import json
import uuid
import os
import logging
from typing import Optional

from sqlalchemy import select

from ...infrastructure.database.models import Document, Chunk, ChunkingStrategy, ProcessingConfig as ProcessingConfigModel
from ...infrastructure.database import async_session_maker
from ...infrastructure.parsers.base import ParserRegistry
from ...domain.services.link_resolver import resolve_links
from ...domain.services.chunking import create_chunking_service
from ...domain.services.embedding import get_embedder, normalize_embedding
from ...core.config import get_settings
from ...core.logging import log_structured

settings = get_settings()
parser_registry = ParserRegistry()
logger = logging.getLogger(__name__)



MAX_RETRIES = 3
RETRY_DELAY = 5


async def update_document_progress(
    document_id: str,
    step: str,
    message: str,
    processed_chars: Optional[int] = None,
    chunk_count: Optional[int] = None,
    expected_config_id: Optional[str] = None,
):
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()
            if document:
                # Stale task detection — if reprocess changed the config, skip
                if (
                    expected_config_id is not None
                    and document.current_processing_config_id != expected_config_id
                ):
                    logger.info(f"Skipping stale progress update for {document_id}: config changed")
                    return
                document.status = "processing"
                document.processing_step = step
                document.processing_message = message
                if processed_chars is not None:
                    document.processed_chars = processed_chars
                if chunk_count is not None:
                    document.chunk_count = chunk_count
                await session.commit()
    except Exception as e:
        logger.warning(f"Failed to update document progress: {e}")


async def mark_document_failed(document_id: str, error: str):
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()
            if document:
                document.status = "failed"
                document.processing_step = "failed"
                document.error_message = error[:1000]
                document.saved_chunks = 0
                await session.commit()
        logger.error(f"Document {document_id} failed: {error}")
    except Exception as e:
        logger.error(f"Failed to mark document as failed: {e}")


def _inject_page_numbers(chunk_data: list[dict]) -> None:
    """Detect ``[Page N]`` markers in chunk content and set ``page_number``
    in each chunk's metadata.

    The PDF parser produces text that starts each page with the marker
    ``[Page N]`` (1-indexed).  When the recursive chunker splits this text
    the marker may fall at the beginning of a chunk.  This function scans
    the first few lines of each chunk for this pattern and records the
    page number so that the link resolver can correctly map links (which
    are page-based) to chunks.

    Chunks without an identifiable marker keep their existing metadata
    unchanged (the link resolver will default to page 1).
    """
    import re
    marker_re = re.compile(r'^\[Page (\d+)\]')

    for chunk in chunk_data:
        content = chunk.get("content", "")
        meta = chunk.setdefault("metadata", {})
        # Only set page_number if not already present (don't overwrite
        # page info that may have been added by a semantic chunker).
        if "page_number" in meta:
            continue
        # Check the first line of the chunk content
        first_line = content.split("\n", 1)[0]
        m = marker_re.match(first_line.strip())
        if m:
            meta["page_number"] = int(m.group(1))


async def process_document_async(document_id: str):
    logger.info(f"Starting document processing: {document_id}")
    retry_count = 0
    
    while retry_count < MAX_RETRIES:
        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    select(Document).where(Document.id == document_id)
                )
                document = result.scalar_one_or_none()
                
                if not document:
                    logger.warning(f"Document {document_id} not found")
                    return
                
                # Load ProcessingConfig if available (Phase 5: Read from ProcessingConfig)
                processing_config = None
                expected_config_id = document.current_processing_config_id
                if document.current_processing_config_id:
                    pc_result = await session.execute(
                        select(ProcessingConfigModel).where(ProcessingConfigModel.id == document.current_processing_config_id)
                    )
                    processing_config = pc_result.scalar_one_or_none()
                
                file_path = document.file_path
                if not os.path.exists(file_path):
                    await mark_document_failed(document_id, f"File not found: {os.path.basename(file_path)}")
                    return
                
                await update_document_progress(
                    document_id,
                    "parsing",
                    f"Parsing {document.doc_type.upper()} file...",
                    expected_config_id=expected_config_id,
                )
                
                try:
                    text = await parser_registry.parse(file_path)
                    if not text or len(text.strip()) < 10:
                        await mark_document_failed(document_id, "Document appears to be empty or unreadable")
                        return
                except Exception as e:
                    await mark_document_failed(document_id, f"Failed to parse document: {str(e)}")
                    return
                
                total_chars = len(text)
                
                async with async_session_maker() as session2:
                    result2 = await session2.execute(
                        select(Document).where(Document.id == document_id)
                    )
                    doc2 = result2.scalar_one_or_none()
                    if doc2:
                        doc2.total_chars = total_chars
                        doc2.processed_chars = total_chars
                        await session2.commit()
                
                await update_document_progress(
                    document_id,
                    "chunking",
                    f"Creating chunks with {settings.default_chunk_size} token size...",
                    expected_config_id=expected_config_id,
                )
                
                # Read params from ProcessingConfig if available, fall back to strategy
                if processing_config:
                    chunk_size = processing_config.chunk_size
                    chunk_overlap = processing_config.chunk_overlap
                    separators = processing_config.separators
                    use_hyperlinks = processing_config.use_hyperlinks
                    engine_type = processing_config.engine_type
                    strategy_name = processing_config.strategy_id
                else:
                    # Fallback to strategy (shouldn't happen for new documents, but handle gracefully)
                    strategy_result = await session.execute(
                        select(ChunkingStrategy).where(ChunkingStrategy.id == document.chunking_strategy_id)
                    )
                    strategy = strategy_result.scalar_one_or_none()
                    
                    if not strategy:
                        chunk_size = settings.default_chunk_size
                        chunk_overlap = settings.default_chunk_overlap
                        separators = ["\n\n", "\n", ". "]
                        use_hyperlinks = False
                        strategy_name = "recursive"
                        engine_type = "recursive"
                    else:
                        chunk_size = strategy.chunk_size
                        chunk_overlap = strategy.chunk_overlap
                        separators = strategy.separators
                        use_hyperlinks = strategy.use_hyperlinks
                        strategy_name = strategy.name
                        engine_type = getattr(strategy, "engine_type", "recursive")
                
                if engine_type == "api-docs":
                    from src.domain.services.api_doc_processor import (
                        _persist_api_doc_index,
                        _process_api_doc,
                        get_api_doc_processing_message,
                    )

                    doc_type = document.doc_type
                    if doc_type not in ("docx", "pdf"):
                        await mark_document_failed(
                            document_id,
                            f"API Documentation strategy only supports DOCX and PDF files, got {doc_type}",
                        )
                        return

                    await update_document_progress(
                        document_id,
                        "extracting",
                        "Extracting API documentation...",
                        expected_config_id=expected_config_id,
                    )

                    try:
                        api_result = await _process_api_doc(
                            document_id, file_path, doc_type, user_id=document.user_id
                        )
                    except Exception as e:
                        logger.error(
                            "API doc processing failed for %s: %s", document_id, e, exc_info=True
                        )
                        await mark_document_failed(
                            document_id, "API doc processing failed - check server logs for details"
                        )
                        return

                    # Persist to ApiDocIndex table
                    try:
                        await _persist_api_doc_index(document_id, user_id=document.user_id)
                    except Exception as e:
                        logger.warning(
                            "Failed to persist API doc index for %s: %s", document_id, e
                        )

                    # Update document status to completed
                    async with async_session_maker() as session_final:
                        result_final = await session_final.execute(
                            select(Document).where(
                                Document.id == document_id
                            )
                        )
                        doc_final = result_final.scalar_one_or_none()
                        if doc_final:
                            doc_final.status = "completed"
                            doc_final.processing_step = "completed"
                            doc_final.processing_message = (
                                "Indexed for API doc querying"
                            )
                            doc_final.chunk_count = api_result.get(
                                "chunk_count", 0
                            )
                            doc_final.embedded = True
                            await session_final.commit()

                    logger.info(
                        "API doc %s processed successfully: %s chunks",
                        document_id,
                        api_result.get("chunk_count", 0),
                    )
                    return

                if engine_type == "semantic":
                    from ...pdf_semantic_chunking.api import chunk_pdf as semantic_chunk_pdf
                    from ...pdf_semantic_chunking.errors import SemanticChunkingError
                    from ...pdf_semantic_chunking.augmentation import build_augmented_text, build_augmented_text_with_links
                    
                    await update_document_progress(
                        document_id,
                        "chunking",
                        "Running semantic chunking pipeline...",
                        expected_config_id=expected_config_id,
                    )
                    
                    try:
                        # Defensive validation of strategy params (defense-in-depth)
                        # API normally validates chunk_size 50-2000 and chunk_overlap 0-500
                        safe_chunk_size = max(50, chunk_size) if chunk_size > 0 else 500
                        safe_chunk_overlap = max(0, min(chunk_overlap, safe_chunk_size))

                        semantic_result = await semantic_chunk_pdf(
                            file_path,
                            chunk_size=safe_chunk_size,
                            chunk_overlap=safe_chunk_overlap,
                        )
                    except SemanticChunkingError as e:
                        error_report = e.to_dict()
                        async with async_session_maker() as err_session:
                            err_doc = await err_session.execute(
                                select(Document).where(Document.id == document_id)
                            )
                            doc = err_doc.scalar_one_or_none()
                            if doc:
                                doc.status = "error"
                                sanitized_report = dict(error_report)
                                if "traceback_summary" in sanitized_report:
                                    del sanitized_report["traceback_summary"]
                                if "exception" in sanitized_report:
                                    sanitized_report["exception"] = str(e.exception)[:200]
                                doc.error_message = json.dumps(sanitized_report)
                                await err_session.commit()
                        logger.error(f"Semantic chunking failed for {document_id}: {error_report}")
                        return
                    except Exception as e:
                        await mark_document_failed(document_id, f"Semantic chunking failed: {str(e)}")
                        return
                    
                    chunk_data = [
                        {"content": c["content"], "chunk_index": c.get("chunk_index", i), "metadata": c.get("metadata")}
                        for i, c in enumerate(semantic_result.get("chunks", []))
                    ]
                    chunk_count = len(chunk_data)
                    
                    # --- Link resolution pass (only if hyperlinks enabled) --------------
                    if use_hyperlinks:
                        try:
                            all_links = await parser_registry.extract_links(file_path)
                            if all_links:
                                resolve_links(chunk_data, all_links)
                        except Exception as e:
                            logger.warning(f"Link extraction/resolution failed (non-fatal): {e}")
                    
                    embedder = None
                    try:
                        embedder = await get_embedder()
                        log_structured("src.domain.services.processor", "embedder_loaded", level=logging.INFO, engine=engine_type)
                    except Exception as e:
                        logger.warning(f"Failed to load embedder: {e}. Continuing without embeddings.")
                    
                    for i, chunk_info in enumerate(chunk_data):
                        content = chunk_info["content"]
                        metadata = chunk_info.get("metadata", {})
                        
                        if use_hyperlinks and (metadata.get("links") or metadata.get("backlinks")):
                            link_target_contents = {}
                            for other_chunk in chunk_data:
                                other_idx = str(other_chunk.get("chunk_index", ""))
                                if other_idx:
                                    link_target_contents[other_idx] = other_chunk.get("content", "")
                            augmented = build_augmented_text_with_links(content, metadata, link_target_contents)
                        else:
                            augmented = build_augmented_text(content, metadata)
                        embedding_vec = None
                        if embedder:
                            try:
                                embedding_vec = await embedder.embed_text(augmented)
                                if settings.embedding_normalization_enabled and embedding_vec:
                                    embedding_vec = normalize_embedding(embedding_vec)
                            except Exception as e:
                                logger.warning(f"Failed to embed chunk {i}: {e}")
                        
                        new_chunk = Chunk(
                            id=str(uuid.uuid4()),
                            document_id=document_id,
                            content=content,
                            chunk_index=chunk_info["chunk_index"],
                            chunk_metadata=metadata,
                            embedding=embedding_vec,
                        )
                        session.add(new_chunk)
                        await session.commit()
                        
                        if i % 10 == 0 or i == chunk_count - 1:
                            await update_document_progress(
                                document_id,
                                "saving",
                                f"Saving chunk {i+1}/{chunk_count}...",
                                processed_chars=None,
                                expected_config_id=expected_config_id,
                            )
                            doc = await session.get(Document, document_id)
                            if doc:
                                # Stale task detection: if reprocess changed the config, abort
                                if doc.current_processing_config_id != expected_config_id:
                                    logger.warning(
                                        f"Stale processing task for {document_id}: "
                                        f"expected_config_id={expected_config_id}, "
                                        f"actual_config_id={doc.current_processing_config_id}, "
                                        "aborting"
                                    )
                                    return
                                doc.saved_chunks = i + 1
                                await session.commit()
                    
                    async with async_session_maker() as session_final:
                        result_final = await session_final.execute(
                            select(Document).where(Document.id == document_id)
                        )
                        doc_final = result_final.scalar_one_or_none()
                        if doc_final:
                            doc_final.status = "completed"
                            doc_final.processing_step = "completed"
                            doc_final.processing_message = f"Successfully processed! Created {chunk_count} chunks."
                            doc_final.chunk_count = chunk_count
                            doc_final.embedded = embedder is not None
                            await session_final.commit()
                    
                    logger.info(f"Document {document_id} processed successfully: {chunk_count} chunks (semantic)")
                    return
                
                from ...domain.entities import ChunkingStrategy as ChunkingStrategyEntity
                # When processing_config is set the strategy DB model is not loaded,
                # so we only read config from the strategy when available.
                _strategy_config = None if processing_config else getattr(strategy, "config", None)
                strategy_entity = ChunkingStrategyEntity(
                    id=strategy_name,
                    name=strategy_name,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    separators=separators,
                    embedding_model=settings.embedding_model,
                    engine_type=engine_type,
                    use_hyperlinks=use_hyperlinks,
                    config=_strategy_config,
                )
                
                chunking_service = create_chunking_service(strategy_entity)
                
                await update_document_progress(
                    document_id,
                    "chunking",
                    "Splitting text into chunks...",
                    expected_config_id=expected_config_id,
                )
                
                try:
                    chunk_data = chunking_service.chunk_text(text)
                except Exception as e:
                    await mark_document_failed(document_id, f"Failed to chunk text: {str(e)}")
                    return
                
                chunk_count = len(chunk_data)

                # --- Inject page numbers into chunk metadata -------------------------
                # The PDF parser outputs "[Page N]\n" markers in the text.  Walk each
                # chunk's content to detect those markers and set page_number so the
                # link resolver can match links (which are page-based) to chunks.
                _inject_page_numbers(chunk_data)

                # --- Link resolution pass (only if hyperlinks enabled) --------------
                if use_hyperlinks:
                    try:
                        all_links = await parser_registry.extract_links(file_path)
                        if all_links:
                            resolve_links(chunk_data, all_links)
                    except Exception as e:
                        logger.warning(f"Link extraction/resolution failed (non-fatal): {e}")
                
                if chunk_count == 0:
                    await mark_document_failed(document_id, "No chunks created from document")
                    return
                
                await update_document_progress(
                    document_id,
                    "saving",
                    f"Saving {chunk_count} chunks to database...",
                    processed_chars=None,
                    chunk_count=chunk_count,
                    expected_config_id=expected_config_id,
                )
                
                embedder = None
                try:
                    embedder = await get_embedder()
                    log_structured("src.domain.services.processor", "embedder_loaded", level=logging.INFO, engine=engine_type)
                except Exception as e:
                    logger.warning(f"Failed to load embedder: {e}. Continuing without embeddings.")

                from ...pdf_semantic_chunking.augmentation import build_augmented_text, build_augmented_text_with_links

                for i, chunk_info in enumerate(chunk_data):
                    content = chunk_info["content"]
                    metadata = chunk_info.get("metadata") or {}
                    
                    # --- Link-aware augmentation (only if hyperlinks enabled) ----------
                    text_to_embed = build_augmented_text(content, metadata)  # Always augment with COM API metadata
                    if use_hyperlinks and (metadata.get("links") or metadata.get("backlinks")):
                        link_target_contents = {}
                        for other_chunk in chunk_data:
                            other_idx = str(other_chunk.get("chunk_index", ""))
                            if other_idx:
                                link_target_contents[other_idx] = other_chunk.get("content", "")
                        text_to_embed = build_augmented_text_with_links(content, metadata, link_target_contents)
                    
                    existing = await session.execute(
                        select(Chunk).where(Chunk.document_id == document_id, Chunk.content == content)
                    )
                    existing_chunk = existing.scalar_one_or_none()
                    if existing_chunk:
                        if existing_chunk.embedding is not None:
                            continue
                        emb = None
                        if embedder:
                            try:
                                emb = await embedder.embed_text(text_to_embed)
                                if settings.embedding_normalization_enabled and emb:
                                    emb = normalize_embedding(emb)
                            except Exception as e:
                                logger.warning(f"Failed to embed chunk: {e}")
                        existing_chunk.embedding = emb
                        await session.commit()
                        continue

                    embedding_vec = None
                    if embedder:
                        try:
                            embedding_vec = await embedder.embed_text(text_to_embed)
                            if settings.embedding_normalization_enabled and embedding_vec:
                                embedding_vec = normalize_embedding(embedding_vec)
                        except Exception as e:
                            logger.warning(f"Failed to embed chunk {i}: {e}")
                    
                    new_chunk = Chunk(
                        id=str(uuid.uuid4()),
                        document_id=document_id,
                        content=content,
                        chunk_index=chunk_info["chunk_index"],
                        chunk_metadata=chunk_info.get("metadata"),
                        embedding=embedding_vec,
                    )
                    session.add(new_chunk)
                    await session.commit()
                    
                    if i % 10 == 0 or i == chunk_count - 1:
                        await update_document_progress(
                            document_id,
                            "saving",
                            f"Saving chunk {i+1}/{chunk_count}...",
                            processed_chars=None,
                            expected_config_id=expected_config_id,
                        )
                        doc = await session.get(Document, document_id)
                        if doc:
                            # Stale task detection: if reprocess changed the config, abort
                            if doc.current_processing_config_id != expected_config_id:
                                logger.warning(
                                    f"Stale processing task for {document_id}: "
                                    f"expected_config_id={expected_config_id}, "
                                    f"actual_config_id={doc.current_processing_config_id}, "
                                    "aborting"
                                )
                                return
                            doc.saved_chunks = i + 1
                            await session.commit()
                
                async with async_session_maker() as session_final:
                    result_final = await session_final.execute(
                        select(Document).where(Document.id == document_id)
                    )
                    doc_final = result_final.scalar_one_or_none()
                    if doc_final:
                        doc_final.status = "completed"
                        doc_final.processing_step = "completed"
                        doc_final.processing_message = f"Successfully processed! Created {chunk_count} chunks."
                        doc_final.chunk_count = chunk_count
                        doc_final.embedded = embedder is not None
                        await session_final.commit()
                
                logger.info(f"Document {document_id} processed successfully: {chunk_count} chunks")
                return
                
        except asyncio.CancelledError:
            logger.info(f"Document processing cancelled: {document_id}")
            await mark_document_failed(document_id, "Processing cancelled")
            raise
        except Exception as e:
            retry_count += 1
            logger.error(f"Document processing attempt {retry_count}/{MAX_RETRIES} failed: {e}")
            if retry_count >= MAX_RETRIES:
                await mark_document_failed(document_id, f"Processing failed after {MAX_RETRIES} attempts: {str(e)}")
                return
            await asyncio.sleep(RETRY_DELAY * retry_count)
    
    await mark_document_failed(document_id, f"Processing failed after {MAX_RETRIES} attempts")


def trigger_document_processing(document_id: str):
    task = asyncio.create_task(process_document_async(document_id))
    task.add_done_callback(
        lambda t: logger.error(f"Document processing task failed: {t.exception()}") if t.done() and t.exception() is not None else None
    )
    return task
