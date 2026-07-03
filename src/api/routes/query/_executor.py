"""Background executor for async RAG query tasks.

Provides the ``execute_rag_query`` function that runs all configured RAG
backends sequentially, updating the TaskManager as each backend completes.
"""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.query._helpers import (
    build_prompt,
    clean_response,
    deduplicate_chunks,
)
from src.api.routes.query._retrieval import retrieve_chunks
from src.api.schemas.query import QueryStartRequest
from src.core.config import get_settings
from src.domain.services.task_manager import (
    BackendResult,
    TaskStatus,
    task_manager,
)
from src.infrastructure.database import async_session_maker
from src.infrastructure.database.models import Chunk, ChunkingStrategy, Document

logger = logging.getLogger(__name__)
settings = get_settings()


async def _execute_cosine_backend(
    db: AsyncSession, request: QueryStartRequest, user_id: str
) -> BackendResult:
    """Execute the cosine-similarity RAG backend and return a BackendResult."""
    start_time = time.time()
    logger.debug("Cosine backend starting for user %s", user_id)

    try:
        # Validate documents
        result = await db.execute(
            select(Document, ChunkingStrategy)
            .join(
                ChunkingStrategy,
                Document.chunking_strategy_id == ChunkingStrategy.id,
            )
            .where(
                Document.id.in_(request.document_ids),
                Document.user_id == user_id,
            )
        )
        doc_strategies = result.all()
        if not doc_strategies:
            return BackendResult(
                backend="cosine",
                answer="No documents found for the query.",
                sources=[],
                error="No documents found",
            )

        use_hyperlinks = doc_strategies[0][1].use_hyperlinks if doc_strategies else False
        effective_link_decay = 0.0 if not use_hyperlinks else request.link_decay_factor

        # Retrieve chunks
        chunks = await retrieve_chunks(
            db,
            user_id=user_id,
            document_ids=request.document_ids,
            question=request.question,
            top_k=request.top_k,
            link_decay_factor=effective_link_decay,
            link_expansion_factor=request.link_expansion_factor,
        )

        if not chunks:
            return BackendResult(
                backend="cosine",
                answer="No relevant content found in the documents.",
                sources=[],
                error="No relevant content",
            )

        deduped = deduplicate_chunks(chunks)

        prompt = build_prompt(
            request.question,
            deduped,
            prompt_sources=request.prompt_sources,
            include_citations=request.include_citations,
            response_length=request.response_length,
        )

        # Call LLM (the MLXLLM._generate_lock will serialize this)
        from src.domain.services.llm import get_llm

        llm = await get_llm()
        answer = await llm.generate(
            prompt,
            max_tokens=request.max_tokens or settings.llm_max_tokens,
            temperature=request.temperature or settings.llm_temperature,
        )

        if request.clean_response:
            answer = clean_response(
                answer, request.response_length, request.include_citations
            )

        if not answer or len(answer.strip()) < 5:
            answer = "I apologize, but I couldn't generate a proper response. Please try rephrasing your question."  # noqa: E501

        sources = [
            {
                "chunk_id": chunk.id,
                "content": chunk.content,
                "score": score,
                "metadata": chunk.chunk_metadata,
            }
            for chunk, score in deduped[: request.prompt_sources]
        ]

        answer_preview = (answer[:120] + "...") if len(answer) > 120 else answer
        logger.info(
            "Cosine backend completed in %.2fs answer_len=%d answer_preview=%s sources=%d",
            time.time() - start_time,
            len(answer),
            answer_preview,
            len(sources),
        )

        return BackendResult(backend="cosine", answer=answer, sources=sources)
    except Exception as exc:
        logger.error("Cosine backend failed: %s", exc, exc_info=True)
        return BackendResult(
            backend="cosine",
            answer="",
            sources=[],
            error="backend_error",
        )


async def _execute_langchain_backend(
    db: AsyncSession, request: QueryStartRequest, user_id: str
) -> BackendResult:
    """Execute the LangChain RAG backend and return a BackendResult."""
    start_time = time.time()
    logger.debug("LangChain backend starting for user %s", user_id)

    try:
        # Validate documents
        result = await db.execute(
            select(Document, ChunkingStrategy)
            .join(
                ChunkingStrategy,
                Document.chunking_strategy_id == ChunkingStrategy.id,
            )
            .where(
                Document.id.in_(request.document_ids),
                Document.user_id == user_id,
            )
        )
        doc_strategies = result.all()
        if not doc_strategies:
            return BackendResult(
                backend="langchain",
                answer="No documents found for the query.",
                sources=[],
                error="No documents found",
            )

        # Get chunks from database
        chunk_results = await db.execute(
            select(Chunk).where(
                Chunk.document_id.in_(request.document_ids),
                Chunk.embedding.isnot(None),
            )
        )
        all_chunks = chunk_results.scalars().all()

        if not all_chunks:
            return BackendResult(
                backend="langchain",
                answer="No chunks found in documents.",
                sources=[],
                error="No chunks found",
            )

        # Get embeddings for chunks
        chunk_embeddings_raw: list[list[float] | None] = [
            c.embedding for c in all_chunks
        ]
        valid_pairs = [
            (c, emb)
            for c, emb in zip(all_chunks, chunk_embeddings_raw)
            if emb is not None
        ]
        all_chunks = [c for c, _ in valid_pairs]
        chunk_embeddings: list[list[float]] = [e for _, e in valid_pairs]

        if not all_chunks:
            return BackendResult(
                backend="langchain",
                answer="No chunks with valid embeddings found.",
                sources=[],
                error="No valid embeddings",
            )

        requested_doc_ids = set(request.document_ids)

        # Build and initialize QA chain
        from src.domain.services.chain_langchain import get_qa_chain

        qa_chain = await get_qa_chain()
        stored_doc_ids = qa_chain.get_document_ids()

        if not qa_chain.is_initialized() or stored_doc_ids != requested_doc_ids:
            logger.info(
                "Reinitializing LangChain QA chain for async task"
            )
            await qa_chain.initialize(
                list(all_chunks),
                chunk_embeddings,
                document_ids=requested_doc_ids,
            )

        # Generate response (handles retrieval + LLM internally)
        response_text, retrieved = await qa_chain.generate(
            question=request.question,
            max_tokens=request.max_tokens or settings.llm_max_tokens,
            temperature=request.temperature or settings.llm_temperature,
            prompt_sources=request.prompt_sources,
            response_length=request.response_length,
            include_citations=request.include_citations,
            top_k=request.top_k,
            clean_response_enabled=request.clean_response,
        )

        if not retrieved:
            return BackendResult(
                backend="langchain",
                answer=response_text or "I don't have enough information to answer this question.",
                sources=[],
            )

        answer = response_text
        if not answer or len(answer.strip()) < 5:
            answer = "I apologize, but I couldn't generate a proper response."

        sources = [
            {
                "chunk_id": r.chunk_id,
                "content": r.content,
                "score": r.score,
                "metadata": r.metadata,
            }
            for r in retrieved
        ]

        logger.info(
            "LangChain backend completed in %.2fs with %d sources",
            time.time() - start_time,
            len(sources),
        )

        return BackendResult(backend="langchain", answer=answer, sources=sources)
    except Exception as exc:
        logger.error("LangChain backend failed: %s", exc, exc_info=True)
        return BackendResult(
            backend="langchain",
            answer="",
            sources=[],
            error="backend_error",
        )


async def _execute_llamaindex_backend(
    db: AsyncSession, request: QueryStartRequest, user_id: str
) -> BackendResult:
    """Execute the LlamaIndex RAG backend and return a BackendResult."""
    start_time = time.time()
    logger.debug("LlamaIndex backend starting for user %s", user_id)

    try:
        # Validate documents
        result = await db.execute(
            select(Document, ChunkingStrategy)
            .join(
                ChunkingStrategy,
                Document.chunking_strategy_id == ChunkingStrategy.id,
            )
            .where(
                Document.id.in_(request.document_ids),
                Document.user_id == user_id,
            )
        )
        doc_strategies = result.all()
        if not doc_strategies:
            return BackendResult(
                backend="llamaindex",
                answer="No documents found for the query.",
                sources=[],
                error="No documents found",
            )

        from src.domain.services.retrieval_llamaindex import get_llamaindex_retriever

        retriever = await get_llamaindex_retriever(db, request.document_ids)

        answer, retrieved = await retriever.generate(
            request.question,
            top_k=request.top_k,
            max_tokens=request.max_tokens or settings.llm_max_tokens,
            temperature=request.temperature or settings.llm_temperature,
            prompt_sources=request.prompt_sources,
            include_citations=request.include_citations,
            response_length=request.response_length,
        )

        if request.clean_response:
            answer = clean_response(
                answer, request.response_length, request.include_citations
            )

        if not answer or len(answer.strip()) < 5:
            answer = "I apologize, but I couldn't generate a proper response."

        sources = [
            {
                "chunk_id": r.chunk_id,
                "content": r.content,
                "score": r.score,
                "metadata": r.metadata,
            }
            for r in retrieved
        ]

        logger.info(
            "LlamaIndex backend completed in %.2fs with %d sources",
            time.time() - start_time,
            len(sources),
        )

        return BackendResult(backend="llamaindex", answer=answer, sources=sources)
    except Exception as exc:
        logger.error("LlamaIndex backend failed: %s", exc, exc_info=True)
        return BackendResult(
            backend="llamaindex",
            answer="",
            sources=[],
            error="backend_error",
        )


async def _execute_api_docs_backend(
    db: AsyncSession, request: QueryStartRequest, user_id: str
) -> BackendResult:
    """Execute the API-docs RAG backend and return a BackendResult."""
    start_time = time.time()
    logger.debug("API-docs backend starting for user %s", user_id)

    try:
        from src.domain.rag.api_docs.manager import get_manager

        manager = get_manager()

        # For async tasks we need a document_id; use the first one from the request
        if not request.document_ids:
            return BackendResult(
                backend="api_docs",
                answer="No document specified for API docs query.",
                sources=[],
                error="No document_ids provided",
            )

        doc_id = request.document_ids[0]

        # Trigger on-the-fly ingestion if not yet indexed
        if not manager.is_indexed(doc_id, user_id=str(user_id)):
            doc_result = await db.execute(
                select(Document).where(
                    Document.id == doc_id,
                    Document.user_id == user_id,
                )
            )
            document = doc_result.scalar_one_or_none()
            if document:
                from src.domain.rag.api_docs.routes import _run_on_the_fly_ingestion

                await _run_on_the_fly_ingestion(
                    document=document,
                    document_id=doc_id,
                    user_id=str(user_id),
                )

        # Run query via the manager
        response = await manager.query(
            document_id=doc_id,
            query_text=request.question,
            top_k=request.top_k,
            rerank_k=20,
            user_id=str(user_id),
            temperature=settings.api_docs_temperature,
            verification_enabled=True,
            max_tokens=request.max_tokens or settings.llm_max_tokens,
        )

        sources = [
            {
                "chunk_id": s.chunk_id,
                "content": s.content,
                "score": s.score,
                "metadata": {
                    "kind": s.kind,
                    "interface_name": s.interface_name,
                    "function_name": s.function_name,
                    "type_name": s.type_name,
                },
            }
            for s in response.sources
        ]

        logger.info(
            "API-docs backend completed in %.2fs with %d sources",
            time.time() - start_time,
            len(sources),
        )

        return BackendResult(
            backend="api_docs",
            answer=response.answer,
            sources=sources,
            confidence=response.confidence,
            relevant_functions=response.relevant_functions,
            relevant_types=response.relevant_types,
            reasoning_hint=response.reasoning_hint,
        )
    except Exception as exc:
        logger.error("API-docs backend failed: %s", exc, exc_info=True)
        return BackendResult(
            backend="api_docs",
            answer="",
            sources=[],
            error="backend_error",
        )


_BACKEND_MAP = {
    "cosine": _execute_cosine_backend,
    "langchain": _execute_langchain_backend,
    "llamaindex": _execute_llamaindex_backend,
    "api_docs": _execute_api_docs_backend,
}


async def execute_rag_query(
    task_id: str,
    request: QueryStartRequest,
    user_id: str,
) -> None:
    """Execute a RAG query in the background, updating TaskManager as backends complete.

    Runs all configured backends sequentially in the order specified by
    the request's ``backends`` list (with ``api_docs`` appended last when
    ``enable_docs`` is set). Each backend executes within a time budget
    computed from the remaining total timeout (300s overall). If a backend
    exceeds its remaining budget, it is cancelled via ``asyncio.wait_for``
    and the loop moves to the next backend. Results arrive in deterministic
    order as each backend completes.
    """
    logger.info(
        "Background task %s starting for user %s with backends: %s",
        task_id,
        user_id,
        request.backends,
    )

    await task_manager.update_status(task_id, TaskStatus.RUNNING)

    # Determine which backends to run
    backends_to_run: list[str] = []
    if request.enable_rag:
        for b in request.backends:
            if b in _BACKEND_MAP:
                backends_to_run.append(b)
    if request.enable_docs and "api_docs" not in backends_to_run:
        backends_to_run.append("api_docs")

    # If no backends, mark as failed
    if not backends_to_run:
        await task_manager.update_status(
            task_id,
            TaskStatus.FAILED,
            error="No valid backends configured",
        )
        return

    async def run_backend(backend_name: str) -> BackendResult:
        """Run a single backend, updating progress and storing results."""
        await task_manager.update_progress(
            task_id, backend_name, f"Starting {backend_name}..."
        )
        try:
            async with async_session_maker() as db:
                result = await _BACKEND_MAP[backend_name](db, request, user_id)
        except Exception as exc:
            logger.error(
                "Backend %s failed with unhandled error: %s",
                backend_name,
                exc,
                exc_info=True,
            )
            result = BackendResult(
                backend=backend_name, answer="", sources=[], error="backend_error"
            )

        await task_manager.append_result(task_id, result)
        status_msg = "completed" if result.error is None else f"failed: {result.error}"
        await task_manager.update_progress(task_id, backend_name, status_msg)
        return result

    # Run all backends sequentially with per-backend and total timeout guards.
    # Sequential execution ensures results arrive in a deterministic order
    # matching the backend list in the request.
    loop_start = time.monotonic()
    total_timeout = 300  # overall timeout for all backends

    for b in backends_to_run:
        elapsed = time.monotonic() - loop_start
        remaining = total_timeout - elapsed
        if remaining <= 0:
            logger.warning(
                "Task %s timed out after %.1fs — skipping remaining backends",
                task_id, elapsed,
            )
            break

        logger.info("Executing backend: %s (task: %s, remaining=%.1fs)", b, task_id, remaining)
        try:
            await asyncio.wait_for(run_backend(b), timeout=remaining)
        except TimeoutError:
            logger.error(
                "Backend %s timed out after %.1fs (task: %s)", b, elapsed + remaining, task_id,
            )
            await task_manager.append_result(
                task_id,
                BackendResult(backend=b, answer="", sources=[], error="timeout"),
            )

    # Check if any succeeded
    task = await task_manager.get_task(task_id)
    if task is None:
        return

    all_errors = [r.error for r in task.results if r.error]
    any_success = any(r.error is None for r in task.results)

    if not any_success:
        error_msg = "; ".join(
            f"{r.backend}: {r.error}" for r in task.results if r.error
        )
        await task_manager.update_status(
            task_id,
            TaskStatus.FAILED,
            error=f"All backends failed: {error_msg}",
        )
    else:
        await task_manager.update_status(task_id, TaskStatus.COMPLETED)
        if all_errors:
            logger.warning(
                "Task %s completed with partial failures: %s",
                task_id,
                "; ".join(all_errors),
            )

    logger.info("Background task %s finished (status=%s)", task_id, task.status)
