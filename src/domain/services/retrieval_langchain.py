import logging
import time
from typing import Protocol, AsyncGenerator, Any
from dataclasses import dataclass, field
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document as LangChainDocument
from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
import numpy as np

from ...core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class RetrievedChunkResult:
    """Result from hybrid retrieval."""
    chunk_id: str
    content: str
    score: float
    metadata: dict | None
    source: str  # "bm25", "faiss", or "hybrid"


class CustomEnsembleRetriever(BaseRetriever):
    """Custom ensemble retriever combining BM25 (sparse) + FAISS (dense)."""
    
    # Use model_config to avoid Pydantic validation issues
    model_config = {"extra": "allow", "frozen": False}
    
    def __init__(
        self,
        retrievers: list,
        weights: list[float] | None = None,
        k: int = 5,
    ):
        super().__init__()
        self.retrievers = retrievers
        self.weights = weights or [0.5] * len(retrievers)
        self.k = k
    
    def _invoke(
        self,
        input: str,
        config: dict | None = None,
        **kwargs: Any,
    ) -> list[LangChainDocument]:
        raise NotImplementedError("Use ainvoke instead")
    
    async def _aget_relevant_documents(
        self,
        query: str,
        k: int | None = None,
        **kwargs: Any,
    ) -> list[LangChainDocument]:
        """Get relevant documents from all retrievers and combine scores."""
        k = k or self.k
        
        all_docs = {}
        all_scores = {}
        
        for retriever in self.retrievers:
            docs = await retriever.ainvoke(query)
            for i, doc in enumerate(docs[:k * 2]):
                doc_key = doc.metadata.get("chunk_id", str(i))
                if doc_key not in all_docs:
                    all_docs[doc_key] = doc
                    all_scores[doc_key] = 0.0
                # Reciprocal rank scoring
                score = 1.0 / (i + 1)
                all_scores[doc_key] += score
        
        # Sort by combined score
        sorted_keys = sorted(all_scores.keys(), key=lambda x: all_scores[x], reverse=True)
        
        results = []
        for key in sorted_keys[:k]:
            results.append(all_docs[key])
        
        return results
    
    def _get_relevant_documents(
        self,
        query: str,
        k: int | None = None,
        **kwargs: Any,
    ) -> list[LangChainDocument]:
        """Sync version - just return basic retrieval from first retriever."""
        import asyncio
        
        # Run async version
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't run sync in async context - return empty
                return []
            return loop.run_until_complete(self._aget_relevant_documents(query, k))
        except:
            return []
    
    async def ainvoke(
        self,
        input: str,
        config: dict | None = None,
        **kwargs: Any,
    ) -> list[LangChainDocument]:
        return await self._aget_relevant_documents(input, **kwargs)


class LangChainRetriever:
    """Hybrid retriever combining BM25 (sparse) + FAISS (dense) using LangChain."""
    
    def __init__(self):
        self._bm25_retriever: BM25Retriever | None = None
        self._faiss_vectorstore: FAISS | None = None
        self._embeddings: HuggingFaceEmbeddings | None = None
        self._ensemble: CustomEnsembleRetriever | None = None
        self._dimension: int = 384  # default for all-MiniLM-L6-v2
        self._index_built = False
        self._chunks = []
    
    async def initialize(self, chunks: list, chunk_embeddings: list[list[float]]) -> None:
        """Initialize the hybrid retriever with chunks and their embeddings."""
        start_time = time.time()
        logger.info(f"Initializing LangChain hybrid retriever with {len(chunks)} chunks")
        
        try:
            # Create LangChain documents
            langchain_docs = []
            self._chunks = chunks
            for i, chunk in enumerate(chunks):
                doc = LangChainDocument(
                    page_content=chunk.content,
                    metadata={
                        "chunk_id": chunk.id,
                        "document_id": chunk.document_id,
                        "chunk_index": chunk.chunk_index,
                        **(chunk.chunk_metadata or {})
                    }
                )
                langchain_docs.append(doc)
            
            if not langchain_docs:
                logger.warning("No documents to index for hybrid retrieval")
                return
            
            # Initialize BM25 retriever
            logger.info("Building BM25 index...")
            self._bm25_retriever = BM25Retriever.from_documents(
                langchain_docs,
                k1=1.5,  # BM25 k1 parameter
                b=0.75    # BM25 b parameter
            )
            logger.info("BM25 index built successfully")
            
            # Initialize FAISS vector store
            logger.info("Building FAISS index...")
            embeddings = await self._get_embeddings()
            if embeddings and chunk_embeddings:
                self._dimension = len(chunk_embeddings[0])  # Get from actual embeddings
            
            # Create FAISS vectorstore from existing embeddings - pass embeddings object
            try:
                if embeddings:
                    self._faiss_vectorstore = FAISS.from_embeddings(
                        text_embeddings=[(doc.page_content, emb) for doc, emb in zip(langchain_docs, chunk_embeddings)],
                        embedding=embeddings,
                        metadatas=[doc.metadata for doc in langchain_docs]
                    )
                else:
                    # Fallback: use zero embeddings if model not available
                    dim = len(chunk_embeddings[0]) if chunk_embeddings else 384
                    self._faiss_vectorstore = FAISS.from_embeddings(
                        text_embeddings=[(doc.page_content, [0.0] * dim) for doc in langchain_docs],
                        embedding=embeddings,
                        metadatas=[doc.metadata for doc in langchain_docs]
                    )
                logger.info("FAISS index built successfully")
            except Exception as e:
                logger.warning(f"FAISS initialization failed, using BM25 only: {e}")
                self._faiss_vectorstore = None
            
            # Create custom ensemble retriever
            logger.info("Creating custom ensemble retriever...")
            retrievers = [self._bm25_retriever]
            weights = [1.0]  # BM25 only if FAISS failed
            
            if self._faiss_vectorstore:
                retrievers.append(self._faiss_vectorstore.as_retriever())
                weights = [0.5, 0.5]  # Equal weight
            
            self._ensemble = CustomEnsembleRetriever(
                retrievers=retrievers,
                weights=weights,
                k=5,
            )
            
            self._index_built = True
            elapsed = time.time() - start_time
            logger.info(f"Hybrid retriever initialized in {elapsed:.2f}s")
            
        except Exception as e:
            logger.error(f"Failed to initialize hybrid retriever: {type(e).__name__}: {e}", exc_info=True)
            raise
    
    async def _get_embeddings(self) -> HuggingFaceEmbeddings:
        """Get or create embeddings model."""
        if self._embeddings is None:
            try:
                self._embeddings = HuggingFaceEmbeddings(
                    model_name=settings.embedding_model,
                    model_kwargs={"device": "cpu"},
                    encode_kwargs={"normalize_embeddings": True}
                )
            except Exception as e:
                logger.warning(f"Failed to load HuggingFace embeddings: {e}")
                return None
        return self._embeddings
    
    async def _get_embedding_function(self):
        """Get embedding function for FAISS."""
        embeddings = await self._get_embeddings()
        if embeddings:
            return embeddings.embed_query
        return None
    
    async def retrieve(
        self,
        question: str,
        top_k: int = 5,
    ) -> list[RetrievedChunkResult]:
        """Retrieve relevant chunks using hybrid retrieval."""
        if not self._index_built or self._ensemble is None:
            logger.warning("Hybrid retriever not initialized")
            return []
        
        try:
            # Use ensemble retriever
            results = await self._ensemble.ainvoke(question, k=top_k)
            
            retrieved = []
            for doc in results:
                chunk_id = doc.metadata.get("chunk_id", "")
                if not chunk_id:
                    chunk_id = doc.metadata.get("id", "")
                
                retrieved.append(RetrievedChunkResult(
                    chunk_id=chunk_id,
                    content=doc.page_content,
                    score=1.0,
                    metadata=doc.metadata,
                    source="hybrid"
                ))
            
            logger.info(f"Retrieved {len(retrieved)} chunks via hybrid retrieval")
            return retrieved
            
        except Exception as e:
            logger.error(f"Hybrid retrieval failed: {type(e).__name__}: {e}")
            return []
    
    async def retrieve_with_scores(
        self,
        question: str,
        question_embedding: list[float],
        top_k: int = 5,
    ) -> list[RetrievedChunkResult]:
        """Retrieve with combined BM25 and FAISS scores."""
        if not self._index_built:
            logger.warning("Hybrid retriever not initialized")
            return []
        
        try:
            # Get BM25 scores
            bm25_results = await self._bm25_retriever.ainvoke(question, k=top_k * 2)
            bm25_scores = {}
            for i, doc in enumerate(bm25_results):
                chunk_id = doc.metadata.get("chunk_id", "")
                bm25_scores[chunk_id] = 1.0 / (i + 1)
            
            # Get FAISS scores
            faiss_results = await self._faiss_vectorstore.as_retriever().ainvoke(question, k=top_k * 2)
            faiss_scores = {}
            for i, doc in enumerate(faiss_results):
                chunk_id = doc.metadata.get("chunk_id", "")
                faiss_scores[chunk_id] = 1.0 / (i + 1)
            
            # Combine all chunks
            all_chunk_ids = set(bm25_scores.keys()) | set(faiss_scores.keys())
            combined = []
            
            for chunk_id in all_chunk_ids:
                bm25_score = bm25_scores.get(chunk_id, 0)
                faiss_score = faiss_scores.get(chunk_id, 0)
                
                # Weighted combination (0.5 * normalized_BM25 + 0.5 * normalized_FAISS)
                combined_score = 0.5 * bm25_score + 0.5 * faiss_score
                
                # Find the content
                content = None
                metadata = {}
                for doc in bm25_results + faiss_results:
                    if doc.metadata.get("chunk_id", "") == chunk_id:
                        content = doc.page_content
                        metadata = doc.metadata
                        break
                
                if content:
                    # Determine primary source
                    source = "hybrid"
                    if bm25_score > faiss_score:
                        source = "bm25"
                    elif faiss_score > bm25_score:
                        source = "faiss"
                    
                    combined.append(RetrievedChunkResult(
                        chunk_id=chunk_id,
                        content=content,
                        score=combined_score,
                        metadata=metadata,
                        source=source
                    ))
            
            # Sort by combined score
            combined.sort(key=lambda x: x.score, reverse=True)
            
            logger.info(f"Retrieved {len(combined)} chunks via hybrid retrieval with scores")
            return combined[:top_k]
            
        except Exception as e:
            logger.error(f"Hybrid retrieval with scores failed: {type(e).__name__}: {e}")
            return []
    
    def is_initialized(self) -> bool:
        return self._index_built
    
    def get_dimension(self) -> int:
        return self._dimension


# Global instance
_hybrid_retriever_instance: LangChainRetriever | None = None


async def get_hybrid_retriever() -> LangChainRetriever:
    """Get or create the global hybrid retriever instance."""
    global _hybrid_retriever_instance
    if _hybrid_retriever_instance is None:
        _hybrid_retriever_instance = LangChainRetriever()
    return _hybrid_retriever_instance


async def build_hybrid_retriever(
    chunks: list,
    chunk_embeddings: list[list[float]],
) -> LangChainRetriever:
    """Build and initialize the hybrid retriever with given chunks."""
    retriever = await get_hybrid_retriever()
    await retriever.initialize(chunks, chunk_embeddings)
    return retriever


def reset_hybrid_retriever() -> None:
    """Reset the hybrid retriever instance."""
    global _hybrid_retriever_instance
    logger.info("Resetting hybrid retriever")
    _hybrid_retriever_instance = None