"""API route definitions for query endpoints."""

import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....core.config import get_settings
from ....infrastructure.database.models import Chunk, ChunkingStrategy, Document, QueryCache, User
from ...dependencies import get_current_user, get_db
from ...schemas import QueryRequest, SourceChunk
from ._helpers import build_prompt, check_cache, clean_response, deduplicate_chunks
from ._retrieval import retrieve_chunks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["Query"])
settings = get_settings()


@router.post("")
async def query_documents(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.debug(f"Query request - user: {current_user.id}, docs: {request.document_ids}")
    start_time = time.time()

    try:
        if not request.document_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one document_id is required",
            )

        result = await db.execute(
            select(Document, ChunkingStrategy)
            .join(ChunkingStrategy, Document.chunking_strategy_id == ChunkingStrategy.id)
            .where(
                Document.id.in_(request.document_ids),
                Document.user_id == current_user.id,
            )
        )
        doc_strategies = result.all()

        logger.info(f"Found {len(doc_strategies)} documents for user")

        if not doc_strategies:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No documents found",
            )

        strategy_id = doc_strategies[0][1].id if doc_strategies else "recursive"
        use_hyperlinks = doc_strategies[0][1].use_hyperlinks if doc_strategies else False
        effective_link_decay = 0.0 if not use_hyperlinks else request.link_decay_factor

        cached, cache_key = await check_cache(
            db, request.document_ids, request.question, strategy_id,
            include_citations=request.include_citations,
            response_length=request.response_length,
            link_decay_factor=effective_link_decay,
            link_expansion_factor=request.link_expansion_factor,
            clean_response=request.clean_response,
        )

        if cached:
            logger.info("Returning cached response")
            sources = []
            if cached.source_chunk_ids:
                for chunk_id in cached.source_chunk_ids:
                    chunk_result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
                    chunk = chunk_result.scalar_one_or_none()
                    if chunk:
                        sources.append(SourceChunk(
                            chunk_id=chunk.id,
                            content=chunk.content,
                            score=0.0,
                            metadata=chunk.chunk_metadata,
                        ))

            return {
                "answer": cached.response_text,
                "sources": [s.model_dump() for s in sources],
                "cached": True,
                "latency_ms": cached.latency_ms,
            }

        chunks = await retrieve_chunks(
            db,
            user_id=current_user.id,
            document_ids=request.document_ids,
            question=request.question,
            top_k=request.top_k,
            link_decay_factor=effective_link_decay,
            link_expansion_factor=request.link_expansion_factor,
        )

        logger.info(f"Retrieved {len(chunks)} chunks")

        if not chunks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No relevant content found in the documents",
            )

        # Deduplicate chunks to avoid duplicate sources
        deduped = deduplicate_chunks(chunks)

        prompt = build_prompt(request.question, deduped, prompt_sources=request.prompt_sources, include_citations=request.include_citations, response_length=request.response_length)  # noqa: E501

        from ....domain.services.llm import get_llm
        llm = await get_llm()

        max_tokens = request.max_tokens or settings.llm_max_tokens
        temperature = request.temperature or settings.llm_temperature
        try:
            full_response = []
            async for token in llm.generate_stream(prompt, max_tokens, temperature):
                full_response.append(token)
        except Exception as e:
            logger.error(f"LLM generation failed: {type(e).__name__}: {e!s}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service temporarily unavailable. Please try again.",
            )

        answer = "".join(full_response)

        # Optional verification step for cosine backend
        if settings.verification_enabled:
            from ....domain.services.verification import ResponseVerifier
            verifier = ResponseVerifier()
            verified = await verifier.verify(answer, deduped[:request.prompt_sources])
            answer = verified.verified_text

        if request.clean_response:
            answer = clean_response(answer, request.response_length, request.include_citations)

        if not answer or len(answer.strip()) < 5:
            logger.warning("LLM returned empty or very short response")
            answer = "I apologize, but I couldn't generate a proper response. Please try rephrasing your question."  # noqa: E501

        if settings.cache_expiry_days > 0:
            query_cache = QueryCache(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                document_id=",".join(sorted(request.document_ids)),
                query_hash=cache_key,
                query_text=request.question,
                response_text=answer,
                source_chunk_ids=[c.id for c, _ in deduped[:request.prompt_sources]],
                chunking_strategy_id=strategy_id,
                embedding_model_version=settings.embedding_model,
                latency_ms=int((time.time() - start_time) * 1000),
                expires_at=datetime.now(UTC) + timedelta(days=settings.cache_expiry_days),
            )

            db.add(query_cache)
            await db.commit()

        sources = [
            SourceChunk(
                chunk_id=chunk.id,
                content=chunk.content,
                score=score,
                metadata=chunk.chunk_metadata,
            )
            for chunk, score in deduped[:request.prompt_sources]
        ]

        logger.info(f"Query completed in {time.time() - start_time:.2f}s")

        return {
            "answer": answer,
            "sources": [s.model_dump() for s in sources],
            "cached": False,
            "latency_ms": int((time.time() - start_time) * 1000),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Query failed: {type(e).__name__}: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process query. Please try again.",
        )


@router.post("/stream")
async def query_documents_stream(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.debug(f"Streaming query - user: {current_user.id}, docs: {request.document_ids}")
    start_time = time.time()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            if not request.document_ids:
                yield f"data: {json.dumps({'error': 'At least one document_id is required'})}\n\n"
                return

            result = await db.execute(
                select(Document, ChunkingStrategy)
                .join(ChunkingStrategy, Document.chunking_strategy_id == ChunkingStrategy.id)
                .where(
                    Document.id.in_(request.document_ids),
                    Document.user_id == current_user.id,
                )
            )
            doc_strategies = result.all()

            if not doc_strategies:
                yield f"data: {json.dumps({'error': 'No documents found'})}\n\n"
                return

            strategy_id = doc_strategies[0][1].id if doc_strategies else "recursive"
            use_hyperlinks = doc_strategies[0][1].use_hyperlinks if doc_strategies else False
            effective_link_decay = 0.0 if not use_hyperlinks else request.link_decay_factor

            cached, cache_key = await check_cache(
                db, request.document_ids, request.question, strategy_id,
                include_citations=request.include_citations,
                response_length=request.response_length,
                link_decay_factor=effective_link_decay,
                link_expansion_factor=request.link_expansion_factor,
                clean_response=request.clean_response,
            )

            if cached:
                sources = []
                if cached.source_chunk_ids:
                    for chunk_id in cached.source_chunk_ids:
                        chunk_result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
                        chunk = chunk_result.scalar_one_or_none()
                        if chunk:
                            sources.append({
                                "chunk_id": chunk.id,
                                "content": chunk.content,
                                "score": 0.0,
                                "metadata": chunk.chunk_metadata,
                            })

                yield f"data: {json.dumps({'sources': sources, 'cached': True, 'include_citations': request.include_citations})}\n\n"  # noqa: E501
                if request.clean_response:
                    clean_cached = clean_response(cached.response_text, response_length="normal", include_citations=False)  # noqa: E501
                else:
                    clean_cached = cached.response_text
                for word in clean_cached.split():
                    yield f"data: {json.dumps({'token': word + ' '})}\n\n"
                yield "data: [DONE]\n\n"
                return

            chunks = await retrieve_chunks(
                db,
                user_id=current_user.id,
                document_ids=request.document_ids,
                question=request.question,
                top_k=request.top_k,
                link_decay_factor=effective_link_decay,
                link_expansion_factor=request.link_expansion_factor,
            )

            if not chunks:
                friendly_message = "I don't have enough information to answer this question."
                yield f"data: {json.dumps({'sources': [], 'cached': False, 'include_citations': request.include_citations})}\n\n"  # noqa: E501
                for word in friendly_message.split():
                    yield f"data: {json.dumps({'token': word + ' '})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Deduplicate chunks to avoid duplicate sources
            deduped = deduplicate_chunks(chunks)

            sources = [
                {
                    "chunk_id": chunk.id,
                    "content": chunk.content,
                    "score": score,
                    "metadata": chunk.chunk_metadata,
                }
                for chunk, score in deduped[:request.prompt_sources]
            ]
            yield f"data: {json.dumps({'sources': sources, 'include_citations': request.include_citations})}\n\n"  # noqa: E501

            prompt = build_prompt(request.question, deduped, prompt_sources=request.prompt_sources, include_citations=request.include_citations, response_length=request.response_length)  # noqa: E501

            from ....domain.services.llm import get_llm
            llm = await get_llm()

            full_response = []
            max_tokens = request.max_tokens or settings.llm_max_tokens
            temperature = request.temperature or settings.llm_temperature
            try:
                async for token in llm.generate_stream(prompt, max_tokens, temperature):
                    full_response.append(token)
            except Exception as e:
                logger.error(f"LLM streaming failed: {type(e).__name__}: {e!s}")
                yield f"data: {json.dumps({'error': 'AI service temporarily unavailable. Please try again.'})}\n\n"  # noqa: E501
                return

            raw_response = "".join(full_response)

            # Optional verification for cosine streaming
            if settings.verification_enabled:
                from ....domain.services.verification import ResponseVerifier
                verifier = ResponseVerifier()
                verified = await verifier.verify(raw_response, deduped[:request.prompt_sources])
                raw_response = verified.verified_text

            if request.clean_response:
                answer = clean_response(raw_response, request.response_length, request.include_citations)  # noqa: E501
            else:
                answer = raw_response

            if not answer or len(answer.strip()) < 5:
                logger.warning("LLM returned empty or very short response")
                answer = "I apologize, but I couldn't generate a proper response. Please try rephrasing your question."  # noqa: E501

            # Stream only the cleaned text (no raw tokens leaked)
            for word in answer.split():
                yield f"data: {json.dumps({'token': word + ' '})}\n\n"

            if settings.cache_expiry_days > 0:
                query_cache = QueryCache(
                    id=str(uuid.uuid4()),
                    user_id=current_user.id,
                    document_id=",".join(sorted(request.document_ids)),
                    query_hash=cache_key,
                    query_text=request.question,
                    response_text=answer,
                    source_chunk_ids=[c.id for c, _ in deduped[:request.prompt_sources]],
                    chunking_strategy_id=strategy_id,
                    embedding_model_version=settings.embedding_model,
                    latency_ms=int((time.time() - start_time) * 1000),
                    expires_at=datetime.now(UTC) + timedelta(days=settings.cache_expiry_days),
                )

                db.add(query_cache)
                await db.commit()

            logger.info(f"Streaming query completed in {time.time() - start_time:.2f}s")
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Streaming query failed: {type(e).__name__}: {e!s}", exc_info=True)
            yield f"data: {json.dumps({'error': 'An error occurred. Please try again.'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# LangChain endpoint using hybrid BM25 + FAISS retrieval
@router.post("/langchain")
async def query_documents_langchain(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Query documents using LangChain hybrid retrieval (BM25 + FAISS)."""
    logger.debug(f"LangChain query - user: {current_user.id}, docs: {request.document_ids}")
    start_time = time.time()

    from ....core.security import generate_cache_key

    try:
        if not request.document_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one document_id is required",
            )

        # Check documents exist
        result = await db.execute(
            select(Document, ChunkingStrategy)
            .join(ChunkingStrategy, Document.chunking_strategy_id == ChunkingStrategy.id)
            .where(
                Document.id.in_(request.document_ids),
                Document.user_id == current_user.id,
            )
        )
        doc_strategies = result.all()

        if not doc_strategies:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No documents found",
            )

        strategy_id = doc_strategies[0][1].id if doc_strategies else "recursive"

        # Check LangChain specific cache
        cache_key = generate_cache_key(
            document_id=",".join(sorted(request.document_ids)),
            query_text=request.question,
            chunking_strategy_id=strategy_id,
            embedding_model=settings.embedding_model,
            response_length=request.response_length,
            link_decay_factor=str(request.link_decay_factor),
            link_expansion_factor=str(request.link_expansion_factor),
            clean_response=str(request.clean_response),
        )
        cache_key_langchain = f"{cache_key}_langchain"  # Separate cache for LangChain

        # Check LangChain specific cache
        if settings.cache_expiry_days > 0:
            result = await db.execute(
                select(QueryCache).where(
                    QueryCache.query_hash == cache_key_langchain,
                    QueryCache.expires_at > datetime.now(UTC),
                )
            )
            cached = result.scalar_one_or_none()
        else:
            cached = None

        if cached:
            logger.info("Returning LangChain cached response")
            sources = []
            if cached.source_chunk_ids:
                for chunk_id in cached.source_chunk_ids:
                    chunk_result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
                    chunk = chunk_result.scalar_one_or_none()
                    if chunk:
                        sources.append(SourceChunk(
                            chunk_id=chunk.id,
                            content=chunk.content,
                            score=0.0,
                            metadata=chunk.chunk_metadata,
                        ))

            return {
                "answer": cached.response_text,
                "sources": [s.model_dump() for s in sources],
                "cached": True,
                "latency_ms": cached.latency_ms,
            }

        # Get chunks from database
        chunk_results = await db.execute(
            select(Chunk).where(
                Chunk.document_id.in_(request.document_ids),
                Chunk.embedding.isnot(None)
            )
        )
        all_chunks = chunk_results.scalars().all()

        if not all_chunks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No chunks found in documents",
            )

        # Get embeddings for chunks (using pre-stored embeddings)
        chunk_embeddings_raw: list[list[float] | None] = [c.embedding for c in all_chunks]

        # Filter out any chunks with None embeddings (defensive, SQL filter should prevent this)
        valid_pairs = [(c, emb) for c, emb in zip(all_chunks, chunk_embeddings_raw) if emb is not None]  # noqa: E501
        if len(valid_pairs) != len(all_chunks):
            logger.warning(f"Filtered {len(all_chunks) - len(valid_pairs)} chunks without embeddings")  # noqa: E501
        all_chunks = [c for c, _ in valid_pairs]
        chunk_embeddings: list[list[float]] = [e for _, e in valid_pairs]

        if not all_chunks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No chunks with valid embeddings found in documents",
            )

        # Build LangChain QA chain
        from ....domain.services.chain_langchain import get_qa_chain
        qa_chain = await get_qa_chain()

        # Get document IDs from request
        requested_doc_ids = set(request.document_ids)
        stored_doc_ids = qa_chain.get_document_ids()

        # Reinitialize if document selection changed
        if not qa_chain.is_initialized() or stored_doc_ids != requested_doc_ids:
            logger.info(f"Document IDs changed or not initialized. Reinitializing QA chain. Previous: {stored_doc_ids}, New: {requested_doc_ids}")  # noqa: E501
            await qa_chain.initialize(list(all_chunks), chunk_embeddings, document_ids=requested_doc_ids)  # noqa: E501

        # Generate response using LangChain QA chain (includes retrieval, verification)
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
            # Return empty retrieval message instead of error
            return {
                "answer": response_text,
                "sources": [],
                "cached": False,
                "latency_ms": int((time.time() - start_time) * 1000),
            }

        answer = response_text

        if not answer or len(answer.strip()) < 5:
            answer = "I apologize, but I couldn't generate a proper response. Please try rephrasing your question."  # noqa: E501

        # Cache (with separate key)
        if settings.cache_expiry_days > 0:
            query_cache = QueryCache(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                document_id=",".join(sorted(request.document_ids)),
                query_hash=cache_key_langchain,
                query_text=request.question,
                response_text=answer,
                source_chunk_ids=[r.chunk_id for r in retrieved],
                chunking_strategy_id=strategy_id,
                embedding_model_version=settings.embedding_model,
                latency_ms=int((time.time() - start_time) * 1000),
                expires_at=datetime.now(UTC) + timedelta(days=settings.cache_expiry_days),
            )

            db.add(query_cache)
            await db.commit()

        sources = [
            SourceChunk(
                chunk_id=r.chunk_id,
                content=r.content,
                score=r.score,
                metadata=r.metadata,
            )
            for r in retrieved
        ]

        logger.info(f"LangChain query completed in {time.time() - start_time:.2f}s")

        return {
            "answer": answer,
            "sources": [s.model_dump() for s in sources],
            "cached": False,
            "latency_ms": int((time.time() - start_time) * 1000),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"LangChain query failed: {type(e).__name__}: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process LangChain query. Please try again.",
        )


@router.post("/langchain/stream")
async def query_documents_langchain_stream(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Streaming query using LangChain hybrid retrieval."""
    logger.debug(f"LangChain streaming query - user: {current_user.id}, docs: {request.document_ids}")  # noqa: E501
    start_time = time.time()

    async def event_generator() -> AsyncGenerator[str, None]:
        from ....core.security import generate_cache_key

        try:
            if not request.document_ids:
                yield f"data: {json.dumps({'error': 'At least one document_id is required'})}\n\n"
                return

            # Check documents
            result = await db.execute(
                select(Document, ChunkingStrategy)
                .join(ChunkingStrategy, Document.chunking_strategy_id == ChunkingStrategy.id)
                .where(
                    Document.id.in_(request.document_ids),
                    Document.user_id == current_user.id,
                )
            )
            doc_strategies = result.all()

            if not doc_strategies:
                yield f"data: {json.dumps({'error': 'No documents found'})}\n\n"
                return

            strategy_id = doc_strategies[0][1].id if doc_strategies else "recursive"

            # Check LangChain specific cache
            cache_key = generate_cache_key(
                document_id=",".join(sorted(request.document_ids)),
                query_text=request.question,
                chunking_strategy_id=strategy_id,
                embedding_model=settings.embedding_model,
                response_length=request.response_length,
                link_decay_factor=str(request.link_decay_factor),
                link_expansion_factor=str(request.link_expansion_factor),
                clean_response=str(request.clean_response),
            )
            cache_key_langchain = f"{cache_key}_langchain"

            if settings.cache_expiry_days > 0:
                result = await db.execute(
                    select(QueryCache).where(
                        QueryCache.query_hash == cache_key_langchain,
                        QueryCache.expires_at > datetime.now(UTC),
                    )
                )
                cached = result.scalar_one_or_none()
            else:
                cached = None

            if cached:
                cached_sources = []
                if cached.source_chunk_ids:
                    for chunk_id in cached.source_chunk_ids:
                        chunk_result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
                        chunk = chunk_result.scalar_one_or_none()
                        if chunk:
                            cached_sources.append({
                                "chunk_id": chunk.id,
                                "content": chunk.content,
                                "score": 0.0,
                                "metadata": chunk.chunk_metadata,
                            })

                yield f"data: {json.dumps({'sources': cached_sources, 'cached': True, 'include_citations': request.include_citations})}\n\n"  # noqa: E501
                if request.clean_response:
                    clean_cached = clean_response(cached.response_text, response_length="normal", include_citations=False)  # noqa: E501
                else:
                    clean_cached = cached.response_text
                for word in clean_cached.split():
                    yield f"data: {json.dumps({'token': word + ' '})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Get chunks
            chunk_results = await db.execute(
                select(Chunk).where(
                    Chunk.document_id.in_(request.document_ids),
                    Chunk.embedding.isnot(None)
                )
            )
            all_chunks = chunk_results.scalars().all()

            if not all_chunks:
                yield f"data: {json.dumps({'error': 'No chunks found'})}\n\n"
                return

            # Get embeddings (using pre-stored embeddings)
            chunk_embeddings_raw: list[list[float] | None] = [c.embedding for c in all_chunks]

            # Filter out any chunks with None embeddings (defensive, SQL filter should prevent this)
            valid_pairs = [(c, emb) for c, emb in zip(all_chunks, chunk_embeddings_raw) if emb is not None]  # noqa: E501
            if len(valid_pairs) != len(all_chunks):
                logger.warning(f"Filtered {len(all_chunks) - len(valid_pairs)} chunks without embeddings")  # noqa: E501
            all_chunks = [c for c, _ in valid_pairs]
            chunk_embeddings: list[list[float]] = [e for _, e in valid_pairs]

            if not all_chunks:
                yield f"data: {json.dumps({'error': 'No chunks with valid embeddings'})}\n\n"
                return

            # Get document IDs from request
            requested_doc_ids = set(request.document_ids)

            # Initialize QA chain
            from ....domain.services.chain_langchain import get_qa_chain
            qa_chain = await get_qa_chain()

            stored_doc_ids = qa_chain.get_document_ids()
            if not qa_chain.is_initialized() or stored_doc_ids != requested_doc_ids:
                logger.info(f"Document IDs changed or not initialized. Reinitializing QA chain for stream. Previous: {stored_doc_ids}, New: {requested_doc_ids}")  # noqa: E501
                await qa_chain.initialize(list(all_chunks), chunk_embeddings, document_ids=requested_doc_ids)  # noqa: E501

            # Generate response using QA chain (includes retrieval, verification)
            response_text = ""
            retrieved = []
            async for resp_text, sources in qa_chain.generate_stream(
                question=request.question,
                max_tokens=request.max_tokens or settings.llm_max_tokens,
                temperature=request.temperature or settings.llm_temperature,
                prompt_sources=request.prompt_sources,
                response_length=request.response_length,
                include_citations=request.include_citations,
                top_k=request.top_k,
                clean_response_enabled=request.clean_response,
            ):
                response_text = resp_text
                retrieved = sources

            if not retrieved:
                friendly_message = response_text if response_text else "I don't have enough information to answer this question."  # noqa: E501
                yield f"data: {json.dumps({'sources': [], 'cached': False, 'include_citations': request.include_citations})}\n\n"  # noqa: E501
                for word in friendly_message.split():
                    yield f"data: {json.dumps({'token': word + ' '})}\n\n"
                yield "data: [DONE]\n\n"
                return

            answer = response_text

            if not answer or len(answer.strip()) < 5:
                answer = "I apologize, but I couldn't generate a proper response."

            # Yield sources before tokens
            sources_data = [
                {
                    "chunk_id": r.chunk_id,
                    "content": r.content,
                    "score": r.score,
                    "metadata": r.metadata,
                }
                for r in retrieved
            ]
            yield f"data: {json.dumps({'sources': sources_data, 'include_citations': request.include_citations})}\n\n"  # noqa: E501

            # Yield verified text as tokens
            for word in answer.split():
                yield f"data: {json.dumps({'token': word + ' '})}\n\n"

            # Cache
            if settings.cache_expiry_days > 0:
                query_cache = QueryCache(
                    id=str(uuid.uuid4()),
                    user_id=current_user.id,
                    document_id=",".join(sorted(request.document_ids)),
                    query_hash=cache_key_langchain,
                    query_text=request.question,
                    response_text=answer,
                    source_chunk_ids=[r.chunk_id for r in retrieved],
                    chunking_strategy_id=strategy_id,
                    embedding_model_version=settings.embedding_model,
                    latency_ms=int((time.time() - start_time) * 1000),
                    expires_at=datetime.now(UTC) + timedelta(days=settings.cache_expiry_days),
                )

                db.add(query_cache)
                await db.commit()

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"LangChain streaming failed: {type(e).__name__}: {e!s}", exc_info=True)
            yield f"data: {json.dumps({'error': 'An error occurred'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# LlamaIndex endpoint using custom SQLite vector store adapter
@router.post("/llamaindex")
async def query_documents_llamaindex(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Query documents using LlamaIndex-style retrieval."""
    logger.debug(f"LlamaIndex query - user: {current_user.id}, docs: {request.document_ids}")
    start_time = time.time()

    from ....core.security import generate_cache_key

    try:
        if not request.document_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one document_id is required",
            )

        # Check documents exist
        result = await db.execute(
            select(Document, ChunkingStrategy)
            .join(ChunkingStrategy, Document.chunking_strategy_id == ChunkingStrategy.id)
            .where(
                Document.id.in_(request.document_ids),
                Document.user_id == current_user.id,
            )
        )
        doc_strategies = result.all()

        if not doc_strategies:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No documents found",
            )

        strategy_id = doc_strategies[0][1].id if doc_strategies else "recursive"

        # Check cache (separate cache key with _llamaindex suffix)
        cache_key = generate_cache_key(
            document_id=",".join(sorted(request.document_ids)),
            query_text=request.question,
            chunking_strategy_id=strategy_id,
            embedding_model=settings.embedding_model,
            response_length=request.response_length,
            link_decay_factor=str(request.link_decay_factor),
            link_expansion_factor=str(request.link_expansion_factor),
            clean_response=str(request.clean_response),
        )
        cache_key_llamaindex = f"{cache_key}_llamaindex"

        # Check LlamaIndex specific cache
        if settings.cache_expiry_days > 0:
            result = await db.execute(
                select(QueryCache).where(
                    QueryCache.query_hash == cache_key_llamaindex,
                    QueryCache.expires_at > datetime.now(UTC),
                )
            )
            cached = result.scalar_one_or_none()
        else:
            cached = None

        if cached:
            logger.info("Returning LlamaIndex cached response")
            sources = []
            if cached.source_chunk_ids:
                for chunk_id in cached.source_chunk_ids:
                    chunk_result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
                    chunk = chunk_result.scalar_one_or_none()
                    if chunk:
                        sources.append(SourceChunk(
                            chunk_id=chunk.id,
                            content=chunk.content,
                            score=0.0,
                            metadata=chunk.chunk_metadata,
                        ))

            return {
                "answer": cached.response_text,
                "sources": [s.model_dump() for s in sources],
                "cached": True,
                "latency_ms": cached.latency_ms,
            }

        # Retrieve using LlamaIndex retriever
        from ....domain.services.retrieval_llamaindex import get_llamaindex_retriever
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
            answer = clean_response(answer, request.response_length, request.include_citations)

        if not answer or len(answer.strip()) < 5:
            answer = "I apologize, but I couldn't generate a proper response. Please try rephrasing your question."  # noqa: E501

        # Cache (with separate key)
        if settings.cache_expiry_days > 0:
            query_cache = QueryCache(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                document_id=",".join(sorted(request.document_ids)),
                query_hash=cache_key_llamaindex,
                query_text=request.question,
                response_text=answer,
                source_chunk_ids=[r.chunk_id for r in retrieved],
                chunking_strategy_id=strategy_id,
                embedding_model_version=settings.embedding_model,
                latency_ms=int((time.time() - start_time) * 1000),
                expires_at=datetime.now(UTC) + timedelta(days=settings.cache_expiry_days),
            )

            db.add(query_cache)
            await db.commit()

        sources = [
            SourceChunk(
                chunk_id=r.chunk_id,
                content=r.content,
                score=r.score,
                metadata=r.metadata,
            )
            for r in retrieved
        ]

        logger.info(f"LlamaIndex query completed in {time.time() - start_time:.2f}s")

        return {
            "answer": answer,
            "sources": [s.model_dump() for s in sources],
            "cached": False,
            "latency_ms": int((time.time() - start_time) * 1000),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"LlamaIndex query failed: {type(e).__name__}: {e!s}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process LlamaIndex query. Please try again.",
        )


@router.post("/llamaindex/stream")
async def query_documents_llamaindex_stream(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Streaming query using LlamaIndex-style retrieval."""
    logger.debug(f"LlamaIndex streaming query - user: {current_user.id}, docs: {request.document_ids}")  # noqa: E501
    start_time = time.time()

    async def event_generator() -> AsyncGenerator[str, None]:
        from ....core.security import generate_cache_key

        try:
            if not request.document_ids:
                yield f"data: {json.dumps({'error': 'At least one document_id is required'})}\n\n"
                return

            # Check documents
            result = await db.execute(
                select(Document, ChunkingStrategy)
                .join(ChunkingStrategy, Document.chunking_strategy_id == ChunkingStrategy.id)
                .where(
                    Document.id.in_(request.document_ids),
                    Document.user_id == current_user.id,
                )
            )
            doc_strategies = result.all()

            if not doc_strategies:
                yield f"data: {json.dumps({'error': 'No documents found'})}\n\n"
                return

            strategy_id = doc_strategies[0][1].id if doc_strategies else "recursive"

            # Check LlamaIndex specific cache
            cache_key = generate_cache_key(
                document_id=",".join(sorted(request.document_ids)),
                query_text=request.question,
                chunking_strategy_id=strategy_id,
                embedding_model=settings.embedding_model,
                response_length=request.response_length,
                link_decay_factor=str(request.link_decay_factor),
                link_expansion_factor=str(request.link_expansion_factor),
                clean_response=str(request.clean_response),
            )
            cache_key_llamaindex = f"{cache_key}_llamaindex"

            if settings.cache_expiry_days > 0:
                result = await db.execute(
                    select(QueryCache).where(
                        QueryCache.query_hash == cache_key_llamaindex,
                        QueryCache.expires_at > datetime.now(UTC),
                    )
                )
                cached = result.scalar_one_or_none()
            else:
                cached = None

            if cached:
                cached_sources = []
                if cached.source_chunk_ids:
                    for chunk_id in cached.source_chunk_ids:
                        chunk_result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
                        chunk = chunk_result.scalar_one_or_none()
                        if chunk:
                            cached_sources.append({
                                "chunk_id": chunk.id,
                                "content": chunk.content,
                                "score": 0.0,
                                "metadata": chunk.chunk_metadata,
                            })

                yield f"data: {json.dumps({'sources': cached_sources, 'cached': True, 'include_citations': request.include_citations})}\n\n"  # noqa: E501
                if request.clean_response:
                    clean_cached = clean_response(cached.response_text, response_length="normal", include_citations=False)  # noqa: E501
                else:
                    clean_cached = cached.response_text
                for word in clean_cached.split():
                    yield f"data: {json.dumps({'token': word + ' '})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Get chunks
            chunk_results = await db.execute(
                select(Chunk).where(Chunk.document_id.in_(request.document_ids))
            )
            all_chunks = chunk_results.scalars().all()

            if not all_chunks:
                yield f"data: {json.dumps({'error': 'No chunks found'})}\n\n"
                return

            # Retrieve using LlamaIndex-style retriever
            from ....domain.services.retrieval_llamaindex import LlamaIndexRetriever
            # SECURITY FIX: Pass document_ids to ensure proper access control
            retriever = LlamaIndexRetriever(db, request.document_ids)

            retrieved = await retriever.retrieve(request.question, top_k=request.top_k)

            if not retrieved:
                friendly_message = "I don't have enough information to answer this question."
                yield f"data: {json.dumps({'sources': [], 'cached': False, 'include_citations': request.include_citations})}\n\n"  # noqa: E501
                for word in friendly_message.split():
                    yield f"data: {json.dumps({'token': word + ' '})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Deduplicate chunks to avoid duplicate sources
            deduped = deduplicate_chunks(retrieved)

            # Get prompt_sources from request or use default
            prompt_sources = request.prompt_sources

            sources = [
                {
                    "chunk_id": r.chunk_id,
                    "content": r.content,
                    "score": r.score,
                    "metadata": r.metadata,
                }
                for r in deduped[:prompt_sources]
            ]
            yield f"data: {json.dumps({'sources': sources, 'include_citations': request.include_citations})}\n\n"  # noqa: E501

            # Generate
            from ....domain.services.llm import get_llm
            llm = await get_llm()

            # Use build_prompt helper instead of inline
            prompt = build_prompt(request.question, deduped, prompt_sources=prompt_sources, include_citations=request.include_citations, response_length=request.response_length)  # noqa: E501

            full_response = []
            max_tokens = request.max_tokens or settings.llm_max_tokens
            temperature = request.temperature or settings.llm_temperature
            try:
                async for token in llm.generate_stream(prompt, max_tokens, temperature):
                    full_response.append(token)
            except Exception as e:
                logger.error(f"LLM streaming failed: {type(e).__name__}: {e}")
                yield f"data: {json.dumps({'error': 'AI service temporarily unavailable'})}\n\n"
                return

            raw_response = "".join(full_response)
            if request.clean_response:
                answer = clean_response(raw_response, request.response_length, request.include_citations)  # noqa: E501
            else:
                answer = raw_response

            if not answer or len(answer.strip()) < 5:
                logger.warning("LLM returned empty or very short response")
                answer = "I apologize, but I couldn't generate a proper response."

            # Stream only the cleaned text (no raw tokens leaked)
            for word in answer.split():
                yield f"data: {json.dumps({'token': word + ' '})}\n\n"

            # Cache
            if settings.cache_expiry_days > 0:
                query_cache = QueryCache(
                    id=str(uuid.uuid4()),
                    user_id=current_user.id,
                    document_id=",".join(sorted(request.document_ids)),
                    query_hash=cache_key_llamaindex,
                    query_text=request.question,
                    response_text=answer,
                    source_chunk_ids=[r.chunk_id for r in deduped[:prompt_sources]],
                    chunking_strategy_id=strategy_id,
                    embedding_model_version=settings.embedding_model,
                    latency_ms=int((time.time() - start_time) * 1000),
                    expires_at=datetime.now(UTC) + timedelta(days=settings.cache_expiry_days),
                )

                db.add(query_cache)
                await db.commit()

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"LlamaIndex streaming failed: {type(e).__name__}: {e!s}", exc_info=True)
            yield f"data: {json.dumps({'error': 'An error occurred'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
