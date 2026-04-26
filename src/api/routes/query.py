import json
import re
import time
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..schemas import QueryRequest, SourceChunk
from ..dependencies import get_db, get_current_user
from ...infrastructure.database.models import User, Document, Chunk, QueryCache, ChunkingStrategy
from ...core.security import generate_cache_key
from ...core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["Query"])
settings = get_settings()


def deduplicate_chunks(chunks: list[tuple[Chunk, float]], threshold: int = 50) -> list[tuple[Chunk, float]]:
    if not chunks:
        return []
    
    seen_signatures = []
    unique_chunks = []
    
    for chunk, score in chunks:
        sig = chunk.content[:threshold].lower().strip()
        if sig not in seen_signatures:
            seen_signatures.append(sig)
            unique_chunks.append((chunk, score))
    
    return unique_chunks


def build_prompt(question: str, context_chunks: list[tuple[Chunk, float]]) -> str:
    context_chunks = deduplicate_chunks(context_chunks)[:3]
    
    context_text = "\n\n".join([
        f"SOURCE {i+1}: {chunk.content[:500]}"
        for i, (chunk, _) in enumerate(context_chunks)
    ])
    
    prompt = f"""Answer the question in 2-3 sentences based ONLY on the sources below.

{context_text}

Question: {question}

Answer:"""
    
    return prompt


def clean_response(text: str) -> str:
    text = text.replace("<|endoftext|>", "")
    text = text.replace("<|eos|>", "")
    text = text.replace("<|eot|>", "")
    text = text.replace("<|end|>", "")
    
    text = text.split("<|")[0] if "<|" in text else text
    text = text.strip()
    
    for token in ["[INST]", "[/INST]", "[SYS]", "[/SYS]", "<<SYS>>", "<</SYS>>"]:
        if token in text:
            text = text.split(token)[-1]
    
    for marker in ["Human:", "human:", "Assistant:", "assistant:", "Question:", "Answer:", "Sources:"]:
        if marker in text:
            text = text.split(marker)[0]
    
    text = text.split("You Can Ask")[0].strip()
    text = text.split("Test Questions")[0].strip()
    text = text.split("Examples:")[0].strip()
    text = text.split("Key Points:")[0].strip()
    
    text = re.sub(r'\[Source \d+\].*?(?=\.|$)', '[Source]', text)
    
    lines = text.split("\n")
    unique_lines = []
    seen = set()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        line_key = line.lower()[:40]
        is_dup = any(line_key in s or s in line_key for s in seen)
        if len(line) > 10 and not is_dup:
            seen.add(line_key)
            unique_lines.append(line)
    
    text = " ".join(unique_lines)
    
    text = re.sub(r'(.{20,})\1{2,}', r'\1', text)
    
    text = text.strip()
    if text and text[-1] not in '.!?)':
        last_period = text.rfind('. ')
        if last_period > len(text) * 0.5:
            text = text[:last_period + 1]
    
    return text.strip()


async def retrieve_chunks(
    db: AsyncSession,
    user_id: str,
    document_ids: list[str],
    question: str,
    top_k: int = 5,
) -> list[tuple[Chunk, float]]:
    from ...domain.services.embedding import get_embedder
    
    logger.info(f"Retrieving chunks - user: {user_id}, docs: {document_ids}, question: {question[:50]}...")
    
    try:
        embedder = await get_embedder()
        logger.info("Embedder loaded successfully")
        
        query_embedding = await embedder.embed_text(question)
        logger.info(f"Query embedding generated, dimension: {len(query_embedding)}")
        
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return []
    
    try:
        result = await db.execute(
            select(Document).where(
                Document.id.in_(document_ids),
                Document.user_id == user_id,
            )
        )
        documents = result.scalars().all()
        logger.info(f"Found {len(documents)} documents for user")
    except Exception as e:
        logger.error(f"Document query failed: {e}")
        return []
    
    if not documents:
        logger.warning("No documents found for user and document_ids")
        return []
    
    try:
        chunk_results = await db.execute(
            select(Chunk).where(Chunk.document_id.in_(document_ids))
        )
        all_chunks = chunk_results.scalars().all()
        logger.info(f"Found {len(all_chunks)} total chunks")
    except Exception as e:
        logger.error(f"Chunk query failed: {e}")
        return []
    
    if not all_chunks:
        logger.warning("No chunks found in documents")
        return []
    
    try:
        chunk_texts = [c.content for c in all_chunks]
        chunk_embeddings = await embedder.embed_texts(chunk_texts)
        logger.info(f"Generated {len(chunk_embeddings)} chunk embeddings")
    except Exception as e:
        logger.error(f"Bulk embedding failed: {e}")
        return []
    
    similarities = []
    for chunk, embedding in zip(all_chunks, chunk_embeddings):
        similarity = sum(q * e for q, e in zip(query_embedding, embedding))
        similarities.append((chunk, similarity))
    
    similarities.sort(key=lambda x: x[1], reverse=True)
    
    top_chunks = similarities[:top_k]
    logger.info(f"Top {len(top_chunks)} chunks with scores: {[(c.id, s) for c, s in top_chunks]}")
    
    return top_chunks


async def check_cache(
    db: AsyncSession,
    document_ids: list[str],
    question: str,
    strategy_id: str,
) -> tuple[QueryCache | None, str]:
    cache_key = generate_cache_key(
        document_id=",".join(sorted(document_ids)),
        query_text=question,
        chunking_strategy_id=strategy_id,
        embedding_model=settings.embedding_model,
    )
    
    result = await db.execute(
        select(QueryCache).where(
            QueryCache.query_hash == cache_key,
            QueryCache.expires_at > datetime.now(timezone.utc),
        )
    )
    cached = result.scalar_one_or_none()
    
    return cached, cache_key


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
        
        from ...domain.services.llm import get_llm
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
            
            from ...domain.services.llm import get_llm
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
    
    from ...domain.services.embedding import get_embedder
    
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
        from ...domain.services.chain_langchain import build_qa_chain, get_qa_chain
        qa_chain = await get_qa_chain()
        
        if not qa_chain.is_initialized():
            await qa_chain.initialize(all_chunks, chunk_embeddings)
        
        # Use LangChain retrieval
        from ...domain.services.retrieval_langchain import get_hybrid_retriever
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
        from ...domain.services.llm import get_llm
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
        from ...domain.services.embedding import get_embedder
        
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
            from ...domain.services.retrieval_langchain import get_hybrid_retriever
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
            from ...domain.services.llm import get_llm
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
