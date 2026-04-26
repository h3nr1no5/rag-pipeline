"""API route definitions for query endpoints."""

import json
import time
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...schemas import QueryRequest, SourceChunk
from ...dependencies import get_db, get_current_user
from ....infrastructure.database.models import User, Document, Chunk, QueryCache, ChunkingStrategy
from ....core.config import get_settings
from ._helpers import build_prompt, clean_response, check_cache
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
    logger.info(f"Query request - user: {current_user.id}, docs: {request.document_ids}")
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
        
        strategy_id = doc_strategies[0][1].id if doc_strategies else "default"
        
        cached, cache_key = await check_cache(
            db, request.document_ids, request.question, strategy_id
        )
        
        if cached:
            logger.info("Returning cached response")
            sources = []
            if cached.source_chunk_ids:
                for chunk_id in cached.source_chunk_ids[:5]:
                    chunk_result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
                    chunk = chunk_result.scalar_one_or_none()
                    if chunk:
                        sources.append(SourceChunk(
                            chunk_id=chunk.id,
                            content=chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
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
            question=request.question
        )
        
        logger.info(f"Retrieved {len(chunks)} chunks")
        
        if not chunks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No relevant content found in the documents",
            )
        
        prompt = build_prompt(request.question, chunks)
        
        from ....domain.services.llm import get_llm
        llm = await get_llm()
        
        try:
            full_response = []
            async for token in llm.generate_stream(prompt, settings.llm_max_tokens, settings.llm_temperature):
                full_response.append(token)
        except Exception as e:
            logger.error(f"LLM generation failed: {type(e).__name__}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service temporarily unavailable. Please try again.",
            )
        
        answer = clean_response("".join(full_response))
        
        if not answer or len(answer.strip()) < 5:
            logger.warning("LLM returned empty or very short response")
            answer = "I apologize, but I couldn't generate a proper response. Please try rephrasing your question."
        
        query_cache = QueryCache(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            document_id=",".join(sorted(request.document_ids)),
            query_hash=cache_key,
            query_text=request.question,
            response_text=answer,
            source_chunk_ids=[c.id for c, _ in chunks[:5]],
            chunking_strategy_id=strategy_id,
            embedding_model_version=settings.embedding_model,
            latency_ms=int((time.time() - start_time) * 1000),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.cache_expiry_days),
        )
        
        db.add(query_cache)
        await db.commit()
        
        sources = [
            SourceChunk(
                chunk_id=chunk.id,
                content=chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
                score=score,
                metadata=chunk.chunk_metadata,
            )
            for chunk, score in chunks[:5]
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
        logger.error(f"Query failed: {type(e).__name__}: {str(e)}", exc_info=True)
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
    logger.info(f"Streaming query - user: {current_user.id}, docs: {request.document_ids}")
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
            
            strategy_id = doc_strategies[0][1].id if doc_strategies else "default"
            
            cached, cache_key = await check_cache(
                db, request.document_ids, request.question, strategy_id
            )
            
            if cached:
                sources = []
                if cached.source_chunk_ids:
                    for chunk_id in cached.source_chunk_ids[:5]:
                        chunk_result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
                        chunk = chunk_result.scalar_one_or_none()
                        if chunk:
                            sources.append({
                                "chunk_id": chunk.id,
                                "content": chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
                                "score": 0.0,
                                "metadata": chunk.chunk_metadata,
                            })
                
                yield f"data: {json.dumps({'sources': sources, 'cached': True})}\n\n"
                clean_cached = clean_response(cached.response_text)
                for word in clean_cached.split():
                    yield f"data: {json.dumps({'token': word + ' '})}\n\n"
                yield "data: [DONE]\n\n"
                return
            
            chunks = await retrieve_chunks(
                db,
                user_id=current_user.id,
                document_ids=request.document_ids,
                question=request.question,
            )
            
            if not chunks:
                yield f"data: {json.dumps({'error': 'No relevant content found'})}\n\n"
                return
            
            sources = [
                {
                    "chunk_id": chunk.id,
                    "content": chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
                    "score": score,
                    "metadata": chunk.chunk_metadata,
                }
                for chunk, score in chunks[:5]
            ]
            yield f"data: {json.dumps({'sources': sources})}\n\n"
            
            prompt = build_prompt(request.question, chunks)
            
            from ....domain.services.llm import get_llm
            llm = await get_llm()
            
            full_response = []
            max_stream_tokens = min(settings.llm_max_tokens, 150)
            try:
                async for token in llm.generate_stream(prompt, max_stream_tokens, settings.llm_temperature):
                    full_response.append(token)
                    yield f"data: {json.dumps({'token': token})}\n\n"
                    if len(full_response) >= max_stream_tokens:
                        break
            except Exception as e:
                logger.error(f"LLM streaming failed: {type(e).__name__}: {str(e)}")
                yield f"data: {json.dumps({'error': 'AI service temporarily unavailable. Please try again.'})}\n\n"
                return
            
            answer = clean_response("".join(full_response))
            
            if not answer or len(answer.strip()) < 5:
                logger.warning("LLM returned empty or very short response")
                answer = "I apologize, but I couldn't generate a proper response. Please try rephrasing your question."
            
            query_cache = QueryCache(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                document_id=",".join(sorted(request.document_ids)),
                query_hash=cache_key,
                query_text=request.question,
                response_text=answer,
                source_chunk_ids=[c.id for c, _ in chunks[:5]],
                chunking_strategy_id=strategy_id,
                embedding_model_version=settings.embedding_model,
                latency_ms=int((time.time() - start_time) * 1000),
                expires_at=datetime.now(timezone.utc) + timedelta(days=settings.cache_expiry_days),
            )
            
            db.add(query_cache)
            await db.commit()
            
            logger.info(f"Streaming query completed in {time.time() - start_time:.2f}s")
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error(f"Streaming query failed: {type(e).__name__}: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'error': 'An error occurred. Please try again.'})}\n\n"
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
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
    logger.info(f"LangChain query - user: {current_user.id}, docs: {request.document_ids}")
    start_time = time.time()
    
    from ....domain.services.embedding import get_embedder
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
        
        strategy_id = doc_strategies[0][1].id if doc_strategies else "default"
        
        # Check cache (separate cache key with _langchain suffix)
        cache_key = generate_cache_key(
            document_id=",".join(sorted(request.document_ids)),
            query_text=request.question,
            chunking_strategy_id=strategy_id,
            embedding_model=settings.embedding_model,
        )
        cache_key_langchain = f"{cache_key}_langchain"  # Separate cache for LangChain
        
        # Check LangChain specific cache
        cached, _ = await check_cache(db, request.document_ids, request.question, strategy_id)
        # Override to check langchain cache
        result = await db.execute(
            select(QueryCache).where(
                QueryCache.query_hash == cache_key_langchain,
                QueryCache.expires_at > datetime.now(timezone.utc),
            )
        )
        cached = result.scalar_one_or_none()
        
        if cached:
            logger.info("Returning LangChain cached response")
            sources = []
            if cached.source_chunk_ids:
                for chunk_id in cached.source_chunk_ids[:5]:
                    chunk_result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
                    chunk = chunk_result.scalar_one_or_none()
                    if chunk:
                        sources.append(SourceChunk(
                            chunk_id=chunk.id,
                            content=chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
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
            select(Chunk).where(Chunk.document_id.in_(request.document_ids))
        )
        all_chunks = chunk_results.scalars().all()
        
        if not all_chunks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No chunks found in documents",
            )
        
        # Get embeddings for chunks
        embedder = await get_embedder()
        chunk_texts = [c.content for c in all_chunks]
        chunk_embeddings = await embedder.embed_texts(chunk_texts)
        
        # Build LangChain QA chain
        from ....domain.services.chain_langchain import build_qa_chain, get_qa_chain
        qa_chain = await get_qa_chain()
        
        if not qa_chain.is_initialized():
            await qa_chain.initialize(all_chunks, chunk_embeddings)
        
        # Use LangChain retrieval
        from ....domain.services.retrieval_langchain import get_hybrid_retriever
        hybrid_retriever = await get_hybrid_retriever()
        
        if not hybrid_retriever.is_initialized():
            await hybrid_retriever.initialize(all_chunks, chunk_embeddings)
        
        # Get query embedding
        query_embedding = await embedder.embed_text(request.question)
        
        # Retrieve using hybrid retriever
        retrieved = await hybrid_retriever.retrieve_with_scores(
            request.question,
            query_embedding,
            top_k=5
        )
        
        if not retrieved:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No relevant content found",
            )
        
        # Generate response using LangChain chain
        from ....domain.services.llm import get_llm
        llm = await get_llm()
        
        # Build prompt with retrieved context
        context_text = "\n\n".join([
            f"SOURCE {i+1}: {r.content[:500]}"
            for i, r in enumerate(retrieved[:3])
        ])
        
        prompt = f"""Answer the question in 2-3 sentences based ONLY on the sources below.

{context_text}

Question: {request.question}

Answer:"""
        
        full_response = []
        async for token in llm.generate_stream(prompt, settings.llm_max_tokens, settings.llm_temperature):
            full_response.append(token)
        
        answer = clean_response("".join(full_response))
        
        if not answer or len(answer.strip()) < 5:
            answer = "I apologize, but I couldn't generate a proper response. Please try rephrasing your question."
        
        # Cache (with separate key)
        query_cache = QueryCache(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            document_id=",".join(sorted(request.document_ids)),
            query_hash=cache_key_langchain,
            query_text=request.question,
            response_text=answer,
            source_chunk_ids=[r.chunk_id for r in retrieved[:5]],
            chunking_strategy_id=strategy_id,
            embedding_model_version=settings.embedding_model,
            latency_ms=int((time.time() - start_time) * 1000),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.cache_expiry_days),
        )
        
        db.add(query_cache)
        await db.commit()
        
        sources = [
            SourceChunk(
                chunk_id=r.chunk_id,
                content=r.content[:200] + "..." if len(r.content) > 200 else r.content,
                score=r.score,
                metadata=r.metadata,
            )
            for r in retrieved[:5]
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
        logger.error(f"LangChain query failed: {type(e).__name__}: {str(e)}", exc_info=True)
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
    logger.info(f"LangChain streaming query - user: {current_user.id}, docs: {request.document_ids}")
    start_time = time.time()
    
    async def event_generator() -> AsyncGenerator[str, None]:
        from ....domain.services.embedding import get_embedder
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
            
            strategy_id = doc_strategies[0][1].id if doc_strategies else "default"
            
            # Check LangChain specific cache
            cache_key = generate_cache_key(
                document_id=",".join(sorted(request.document_ids)),
                query_text=request.question,
                chunking_strategy_id=strategy_id,
                embedding_model=settings.embedding_model,
            )
            cache_key_langchain = f"{cache_key}_langchain"
            
            result = await db.execute(
                select(QueryCache).where(
                    QueryCache.query_hash == cache_key_langchain,
                    QueryCache.expires_at > datetime.now(timezone.utc),
                )
            )
            cached = result.scalar_one_or_none()
            
            if cached:
                sources = []
                if cached.source_chunk_ids:
                    for chunk_id in cached.source_chunk_ids[:5]:
                        chunk_result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
                        chunk = chunk_result.scalar_one_or_none()
                        if chunk:
                            sources.append({
                                "chunk_id": chunk.id,
                                "content": chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
                                "score": 0.0,
                                "metadata": chunk.chunk_metadata,
                            })
                
                yield f"data: {json.dumps({'sources': sources, 'cached': True})}\n\n"
                clean_cached = clean_response(cached.response_text)
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
            
            # Get embeddings
            embedder = await get_embedder()
            chunk_texts = [c.content for c in all_chunks]
            chunk_embeddings = await embedder.embed_texts(chunk_texts)
            
            # Initialize hybrid retriever
            from ....domain.services.retrieval_langchain import get_hybrid_retriever
            hybrid_retriever = await get_hybrid_retriever()
            
            if not hybrid_retriever.is_initialized():
                await hybrid_retriever.initialize(all_chunks, chunk_embeddings)
            
            # Get query embedding
            query_embedding = await embedder.embed_text(request.question)
            
            # Retrieve
            retrieved = await hybrid_retriever.retrieve_with_scores(
                request.question,
                query_embedding,
                top_k=5
            )
            
            if not retrieved:
                yield f"data: {json.dumps({'error': 'No relevant content found'})}\n\n"
                return
            
            sources = [
                {
                    "chunk_id": r.chunk_id,
                    "content": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                    "score": r.score,
                    "metadata": r.metadata,
                }
                for r in retrieved[:5]
            ]
            yield f"data: {json.dumps({'sources': sources})}\n\n"
            
            # Generate
            from ....domain.services.llm import get_llm
            llm = await get_llm()
            
            context_text = "\n\n".join([
                f"SOURCE {i+1}: {r.content[:500]}"
                for i, r in enumerate(retrieved[:3])
            ])
            
            prompt = f"""Answer the question in 2-3 sentences based ONLY on the sources below.

{context_text}

Question: {request.question}

Answer:"""
            
            full_response = []
            max_stream_tokens = min(settings.llm_max_tokens, 150)
            try:
                async for token in llm.generate_stream(prompt, max_stream_tokens, settings.llm_temperature):
                    full_response.append(token)
                    yield f"data: {json.dumps({'token': token})}\n\n"
                    if len(full_response) >= max_stream_tokens:
                        break
            except Exception as e:
                logger.error(f"LLM streaming failed: {type(e).__name__}: {e}")
                yield f"data: {json.dumps({'error': 'AI service temporarily unavailable'})}\n\n"
                return
            
            answer = clean_response("".join(full_response))
            
            if not answer or len(answer.strip()) < 5:
                answer = "I apologize, but I couldn't generate a proper response."
            
            # Cache
            query_cache = QueryCache(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                document_id=",".join(sorted(request.document_ids)),
                query_hash=cache_key_langchain,
                query_text=request.question,
                response_text=answer,
                source_chunk_ids=[r.chunk_id for r in retrieved[:5]],
                chunking_strategy_id=strategy_id,
                embedding_model_version=settings.embedding_model,
                latency_ms=int((time.time() - start_time) * 1000),
                expires_at=datetime.now(timezone.utc) + timedelta(days=settings.cache_expiry_days),
            )
            
            db.add(query_cache)
            await db.commit()
            
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error(f"LangChain streaming failed: {type(e).__name__}: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'error': 'An error occurred'})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )