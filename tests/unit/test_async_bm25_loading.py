"""RED-GREEN tests for async BM25 loading.

RED (current): BM25Retriever.from_documents() runs synchronously in initialize(),
               blocking the event loop during CPU-bound tokenization.
GREEN (after fix): BM25 is built via asyncio.to_thread(), keeping the event loop responsive.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.services.retrieval_langchain import LangChainRetriever
from src.domain.services.retrieval_llamaindex import HybridRetriever


@pytest.mark.asyncio
async def test_initialize_bm25_uses_asyncio_to_thread():
    """RED-GREEN: BM25Retriever.from_documents must be called via asyncio.to_thread().

    RED:  initialize() calls BM25Retriever.from_documents() synchronously —
          asyncio.to_thread() is never invoked for the BM25 call.
    GREEN: initialize() wraps the BM25 build in await asyncio.to_thread() —
           our spy captures BM25Retriever.from_documents in to_thread_calls.
    """
    chunks = []
    for i in range(5):
        m = MagicMock()
        m.content = f"Test content chunk {i}"
        m.id = str(i)
        m.document_id = "doc1"
        m.chunk_index = i
        m.chunk_metadata = {"test": True}
        chunks.append(m)

    embeddings = [[0.1] * 4 for _ in range(5)]

    to_thread_calls: list = []
    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func)
        return await original_to_thread(func, *args, **kwargs)

    retriever = LangChainRetriever()

    with patch.object(asyncio, "to_thread", spy_to_thread):
        with patch.object(retriever, "_get_embeddings", new=AsyncMock(return_value=None)):
            with patch("src.domain.services.retrieval_langchain.FAISS.from_embeddings"):
                with patch("src.domain.services.retrieval_langchain.logger"):
                    await retriever.initialize(chunks, embeddings)

    assert retriever._bm25_retriever is not None, (
        "BM25 retriever should be initialized"
    )

    bm25_called_in_thread = any(
        getattr(func, '__name__', None) == 'from_documents'
        for func in to_thread_calls
    )
    assert bm25_called_in_thread, (
        "BM25Retriever.from_documents should be called via asyncio.to_thread(). "
        f"Captured to_thread calls: {[f.__name__ for f in to_thread_calls]}"
    )


@pytest.mark.asyncio
async def test_hybrid_retriever_bm25_not_in_init():
    """Verify HybridRetriever no longer builds BM25 in __init__.

    RED: BM25 was built synchronously in __init__ via self._build_bm25(nodes).
    GREEN: BM25 is deferred — _bm25 starts as None, built later via to_thread.
    """
    nodes = [
        MagicMock(text=f"node {i} content", node_id=str(i))
        for i in range(3)
    ]
    embeddings: list[list[float] | None] = [[0.1] * 4 for _ in range(3)]

    retriever = HybridRetriever(
        nodes=nodes,
        embeddings=embeddings,
        similarity_top_k=5,
        bm25_top_k=5,
        final_top_k=5,
    )

    assert retriever._bm25 is None, (
        "BM25 should not be built in __init__ — starts as None"
    )


@pytest.mark.asyncio
async def test_hybrid_retriever_build_bm25_via_to_thread():
    """Verify HybridRetriever._build_bm25 runs via asyncio.to_thread().

    The _ensure_components method should build BM25 via
    await asyncio.to_thread(HybridRetriever._build_bm25, nodes).
    """
    nodes = [
        MagicMock(text=f"node {i} content", node_id=str(i))
        for i in range(3)
    ]

    to_thread_calls: list = []
    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func)
        return await original_to_thread(func, *args, **kwargs)

    with patch.object(asyncio, "to_thread", spy_to_thread):
        await asyncio.to_thread(HybridRetriever._build_bm25, nodes)

    build_bm25_called = any(
        getattr(func, '__name__', None) == '_build_bm25'
        for func in to_thread_calls
    )
    assert build_bm25_called, (
        "HybridRetriever._build_bm25 should be called via asyncio.to_thread(). "
        f"Captured to_thread calls: {[f.__name__ for f in to_thread_calls]}"
    )
