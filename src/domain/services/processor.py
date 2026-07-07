import asyncio
import json
import logging
import os
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...core.logging import log_structured
from ...domain.services.chunking import create_chunking_service
from ...domain.services.embedding import get_embedder, normalize_embedding
from ...domain.services.link_resolver import resolve_links
from ...infrastructure.database import async_session_maker
from ...infrastructure.database.models import Chunk, ChunkingStrategy, Document
from ...infrastructure.database.models import ProcessingConfig as ProcessingConfigModel
from ...infrastructure.parsers.base import ParserRegistry

settings = get_settings()
parser_registry = ParserRegistry()
logger = logging.getLogger(__name__)



MAX_RETRIES = 3
RETRY_DELAY = 5


async def update_document_progress(
    document_id: str,
    step: str,
    message: str,
    processed_chars: int | None = None,
    chunk_count: int | None = None,
    expected_config_id: str | None = None,
    session: AsyncSession | None = None,
):
    if session is not None:
        try:
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
                    logger.debug(
                        f"Skipping stale progress update for {document_id}: config changed"
                    )
                    return
                document.status = "processing"
                document.processing_step = step
                document.processing_message = message
                if processed_chars is not None:
                    document.processed_chars = processed_chars
                if chunk_count is not None:
                    document.chunk_count = chunk_count
                await session.flush()
        except Exception as e:
            logger.warning(f"Failed to update document progress: {e}")
    else:
        try:
            async with async_session_maker() as own_session:
                result = await own_session.execute(
                    select(Document).where(Document.id == document_id)
                )
                document = result.scalar_one_or_none()
                if document:
                    # Stale task detection — if reprocess changed the config, skip
                    if (
                        expected_config_id is not None
                        and document.current_processing_config_id != expected_config_id
                    ):
                        logger.debug(
                            f"Skipping stale progress update for {document_id}: config changed"
                        )
                        return
                    document.status = "processing"
                    document.processing_step = step
                    document.processing_message = message
                    if processed_chars is not None:
                        document.processed_chars = processed_chars
                    if chunk_count is not None:
                        document.chunk_count = chunk_count
                    await own_session.commit()
        except Exception as e:
            logger.warning(f"Failed to update document progress: {e}")


async def mark_document_failed(document_id: str, error: str, session: AsyncSession | None = None):
    if session is not None:
        try:
            async with session.begin_nested():
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
        except Exception as e:
            logger.error(f"Failed to mark document as failed: {e}")
    else:
        try:
            async with async_session_maker() as own_session:
                result = await own_session.execute(
                    select(Document).where(Document.id == document_id)
                )
                document = result.scalar_one_or_none()
                if document:
                    document.status = "failed"
                    document.processing_step = "failed"
                    document.error_message = error[:1000]
                    document.saved_chunks = 0
                await own_session.commit()
        except Exception as e:
            logger.error(f"Failed to mark document as failed: {e}")
    logger.error(f"Document {document_id} failed: {error}")


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
    logger.debug(f"Starting document processing: {document_id}")
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
                        select(ProcessingConfigModel).where(ProcessingConfigModel.id == document.current_processing_config_id)  # noqa: E501
                    )
                    processing_config = pc_result.scalar_one_or_none()

                file_path = document.file_path
                if not os.path.exists(file_path):
                    await mark_document_failed(document_id, f"File not found: {os.path.basename(file_path)}", session=session)  # noqa: E501
                    return

                await update_document_progress(
                    document_id,
                    "parsing",
                    f"Parsing {document.doc_type.upper()} file...",
                    expected_config_id=expected_config_id,
                    session=session,
                )

                try:
                    text = await parser_registry.parse(file_path)
                    if not text or len(text.strip()) < 10:
                        await mark_document_failed(document_id, "Document appears to be empty or unreadable", session=session)  # noqa: E501
                        return
                except Exception as e:
                    await mark_document_failed(
                        document_id, f"Failed to parse document: {e!s}", session=session
                    )
                    return

                total_chars = len(text)

                # Use main session for total_chars update (avoids redundant session)
                document.total_chars = total_chars
                document.processed_chars = total_chars
                await session.flush()

                await update_document_progress(
                    document_id,
                    "chunking",
                    f"Creating chunks with {settings.default_chunk_size} token size...",
                    expected_config_id=expected_config_id,
                    session=session,
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
                    # Fallback to strategy (shouldn't happen for new documents, but handle gracefully)  # noqa: E501
                    strategy_result = await session.execute(
                        select(ChunkingStrategy).where(ChunkingStrategy.id == document.chunking_strategy_id)  # noqa: E501
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
                    )

                    doc_type = document.doc_type
                    if doc_type not in ("docx", "pdf"):
                        await mark_document_failed(
                            document_id,
                            f"API Documentation strategy only supports DOCX and PDF files, got {doc_type}",  # noqa: E501
                            session=session,
                        )
                        return

                    await update_document_progress(
                        document_id,
                        "extracting",
                        "Extracting API documentation...",
                        expected_config_id=expected_config_id,
                        session=session,
                    )

                    try:
                        # ProgressReporter that writes updates to the DB.
                        class _ApiDocProgressReporter:
                            """Writes progress updates to the database."""
                            def __init__(
                                self, doc_id: str, ecid: str | None,
                                session: AsyncSession | None = None,
                            ) -> None:
                                self._doc_id = doc_id
                                self._ecid = ecid
                                self._session = session

                            async def report(self, step: str, message: str) -> None:
                                await update_document_progress(
                                    self._doc_id, step, message,
                                    expected_config_id=self._ecid,
                                    session=self._session,
                                )

                        api_result = await _process_api_doc(
                            document_id, file_path, doc_type,
                            user_id=document.user_id,
                            progress_callback=_ApiDocProgressReporter(
                                document_id, expected_config_id, session=session
                            ),
                        )
                    except Exception as e:
                        logger.error(
                            "API doc processing failed for %s: %s", document_id, e, exc_info=True
                        )
                        await mark_document_failed(
                            document_id,
                            "API doc processing failed - check server logs for details",
                            session=session,
                        )
                        return

                    # Persist to ApiDocIndex table
                    try:
                        await _persist_api_doc_index(
                            document_id, user_id=document.user_id, session=session
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to persist API doc index for %s: %s", document_id, e
                        )

                    # Update document status to completed (using main session)
                    document.status = "completed"
                    document.processing_step = "completed"
                    document.processing_message = "Indexed for API doc querying"
                    document.chunk_count = api_result.get("chunk_count", 0)
                    document.embedded = True
                    await session.commit()

                    logger.info(
                        "API doc %s processed successfully: %s chunks",
                        document_id,
                        api_result.get("chunk_count", 0),
                    )
                    return

                if engine_type == "semantic":
                    from ...pdf_semantic_chunking.api import chunk_pdf as semantic_chunk_pdf
                    from ...pdf_semantic_chunking.augmentation import (
                        build_augmented_text,
                        build_augmented_text_with_links,
                    )
                    from ...pdf_semantic_chunking.errors import SemanticChunkingError

                    await update_document_progress(
                        document_id,
                        "chunking",
                        "Running semantic chunking pipeline...",
                        expected_config_id=expected_config_id,
                        session=session,
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
                        async with session.begin_nested():
                            err_doc = await session.execute(
                                select(Document).where(Document.id == document_id)
                            )
                            doc = err_doc.scalar_one_or_none()
                            if doc:
                                doc.status = "error"
                                sanitized_report = dict(error_report)
                                sanitized_report.pop("traceback_summary", None)
                                if "exception" in sanitized_report:
                                    sanitized_report["exception"] = str(e.exception)[:200]
                                doc.error_message = json.dumps(sanitized_report)
                            await session.commit()
                        logger.error(f"Semantic chunking failed for {document_id}: {error_report}")
                        return
                    except Exception as e:
                        await mark_document_failed(
                            document_id, f"Semantic chunking failed: {e!s}", session=session
                        )
                        return

                    chunk_data = [
                        {"content": c["content"], "chunk_index": c.get("chunk_index", i), "metadata": c.get("metadata")}  # noqa: E501
                        for i, c in enumerate(semantic_result.get("chunks", []))
                    ]
                    chunk_count = len(chunk_data)

                    if chunk_count == 0:
                        await mark_document_failed(
                            document_id, "No chunks created from document", session=session
                        )
                        return

                    # --- Inject page numbers into chunk metadata -------------------------
                    _inject_page_numbers(chunk_data)

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
                        log_structured("src.domain.services.processor", "embedder_loaded", level=logging.INFO, engine=engine_type)  # noqa: E501
                    except Exception as e:
                        logger.warning(f"Failed to load embedder: {e}. Continuing without embeddings.")  # noqa: E501

                    for i, chunk_info in enumerate(chunk_data):
                        content = chunk_info["content"]
                        metadata = chunk_info.get("metadata", {})

                        if use_hyperlinks and (metadata.get("links") or metadata.get("backlinks")):
                            link_target_contents = {}
                            for other_chunk in chunk_data:
                                other_idx = str(other_chunk.get("chunk_index", ""))
                                if other_idx:
                                    link_target_contents[other_idx] = other_chunk.get("content", "")
                            augmented = build_augmented_text_with_links(content, metadata, link_target_contents)  # noqa: E501
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
                        await session.flush()

                        if i % 10 == 0 or i == chunk_count - 1:
                            await update_document_progress(
                                document_id,
                                "saving",
                                f"Saving chunk {i+1}/{chunk_count}...",
                                processed_chars=None,
                                expected_config_id=expected_config_id,
                                session=session,
                            )
                            await session.commit()  # Full commit at batch boundary
                            doc = await session.get(Document, document_id)  # Stale: fresh data
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

                    # Final safety commit for any remaining uncommitted data
                    await session.commit()

                    # Update document status to completed (using main session)
                    document.status = "completed"
                    document.processing_step = "completed"
                    document.processing_message = f"Successfully processed! Created {chunk_count} chunks."  # noqa: E501
                    document.chunk_count = chunk_count
                    document.embedded = embedder is not None
                    await session.commit()

                    logger.debug(f"Document {document_id} processed successfully: {chunk_count} chunks (semantic)")  # noqa: E501
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
                    session=session,
                )

                try:
                    chunk_data = chunking_service.chunk_text(text)
                except Exception as e:
                    await mark_document_failed(
                        document_id, f"Failed to chunk text: {e!s}", session=session
                    )
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
                    await mark_document_failed(
                        document_id, "No chunks created from document", session=session
                    )
                    return

                await update_document_progress(
                    document_id,
                    "saving",
                    f"Saving {chunk_count} chunks to database...",
                    processed_chars=None,
                    chunk_count=chunk_count,
                    expected_config_id=expected_config_id,
                    session=session,
                )

                embedder = None
                try:
                    embedder = await get_embedder()
                    log_structured("src.domain.services.processor", "embedder_loaded", level=logging.INFO, engine=engine_type)  # noqa: E501
                except Exception as e:
                    logger.warning(f"Failed to load embedder: {e}. Continuing without embeddings.")

                from ...pdf_semantic_chunking.augmentation import (
                    build_augmented_text,
                    build_augmented_text_with_links,
                )

                for i, chunk_info in enumerate(chunk_data):
                    content = chunk_info["content"]
                    metadata = chunk_info.get("metadata") or {}

                    # --- Link-aware augmentation (only if hyperlinks enabled) ----------
                    text_to_embed = build_augmented_text(content, metadata)  # Always augment with COM API metadata  # noqa: E501
                    if use_hyperlinks and (metadata.get("links") or metadata.get("backlinks")):
                        link_target_contents = {}
                        for other_chunk in chunk_data:
                            other_idx = str(other_chunk.get("chunk_index", ""))
                            if other_idx:
                                link_target_contents[other_idx] = other_chunk.get("content", "")
                        text_to_embed = build_augmented_text_with_links(content, metadata, link_target_contents)  # noqa: E501

                    existing = await session.execute(
                        select(Chunk).where(Chunk.document_id == document_id, Chunk.content == content)  # noqa: E501
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
                        await session.flush()
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
                    await session.flush()

                    if i % 10 == 0 or i == chunk_count - 1:
                        await update_document_progress(
                            document_id,
                            "saving",
                            f"Saving chunk {i+1}/{chunk_count}...",
                            processed_chars=None,
                            expected_config_id=expected_config_id,
                            session=session,
                        )
                        await session.commit()  # Full commit at batch boundary
                        doc = await session.get(Document, document_id)  # Stale: fresh data
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

                # Final safety commit for any remaining uncommitted data
                await session.commit()

                # Update document status to completed (using main session)
                document.status = "completed"
                document.processing_step = "completed"
                document.processing_message = f"Successfully processed! Created {chunk_count} chunks."  # noqa: E501
                document.chunk_count = chunk_count
                document.embedded = embedder is not None
                await session.commit()

                logger.debug(f"Document {document_id} processed successfully: {chunk_count} chunks")
                return

        except asyncio.CancelledError:
            logger.debug(f"Document processing cancelled: {document_id}")
            await mark_document_failed(document_id, "Processing cancelled")
            raise
        except Exception as e:
            retry_count += 1
            logger.error(f"Document processing attempt {retry_count}/{MAX_RETRIES} failed: {e}")
            if retry_count >= MAX_RETRIES:
                await mark_document_failed(document_id, f"Processing failed after {MAX_RETRIES} attempts: {e!s}")  # noqa: E501
                return
            await asyncio.sleep(RETRY_DELAY * retry_count)

    await mark_document_failed(document_id, f"Processing failed after {MAX_RETRIES} attempts")


def trigger_document_processing(document_id: str):
    task_name = f"process_doc_{document_id[:8]}"
    task = asyncio.create_task(process_document_async(document_id), name=task_name)
    task.add_done_callback(
        lambda t: logger.error(f"Document processing task failed: {t.exception()}") if t.done() and t.exception() is not None else None  # noqa: E501
    )
    return task
