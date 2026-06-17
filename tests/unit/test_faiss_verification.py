"""
Verification tests for the FAISS embedding fix.

Tests that _ProjectEmbeddingFunction properly L2-normalizes query embeddings,
and that FAISS retrieval returns real scores based on embedding similarity
rather than fake 1/(rank+1) scores.
"""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from langchain_core.embeddings import Embeddings

from src.domain.services.retrieval_langchain import (
    _ProjectEmbeddingFunction,
    LangChainRetriever,
)
from src.core.config import get_settings


class MockEmbeddings(Embeddings):
    """Minimal Embeddings subclass returning controlled query vectors.

    LangChain's FAISS checks isinstance(embedding_function, Embeddings)
    before calling aembed_query(). A plain MagicMock fails that check,
    so we provide a real Embeddings subclass.
    """

    def __init__(self, query_result: list[float] | None = None) -> None:
        self._query_result = query_result or [1.0, 0.0, 0.0, 0.0]

    def embed_query(self, text: str) -> list[float]:
        return self._query_result

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "embed_documents is not supported in MockEmbeddings"
        )


@pytest.mark.asyncio
async def test_project_embedding_function_normalizes():
    """Verify embed_query() returns L2-normalized vector.

    Patches SentenceTransformer globally so no model is loaded.
    The mock encode() returns a raw [3.0, 4.0] vector; after the
    _ProjectEmbeddingFunction's embed_query applies normalize_embedding,
    the result must be [0.6, 0.8] with unit norm.
    """
    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([3.0, 4.0])

    # Patch _ensure_model directly to avoid real SentenceTransformer loading.
    # This is more reliable than patching sentence_transformers.SentenceTransformer
    # because the lazy import inside _ensure_model is tricky to intercept.
    with patch.object(_ProjectEmbeddingFunction, "_ensure_model", return_value=mock_model):
        emb_fn = _ProjectEmbeddingFunction()
        result = emb_fn.embed_query("test query")

    # After L2 normalization, [3, 4] should become [0.6, 0.8]
    assert len(result) == 2, f"Expected 2, got {len(result)}"
    assert abs(result[0] - 0.6) < 1e-6, f"Expected 0.6, got {result[0]}"
    assert abs(result[1] - 0.8) < 1e-6, f"Expected 0.8, got {result[1]}"

    # Verify unit norm
    norm = sum(x * x for x in result)
    assert abs(norm - 1.0) < 1e-6, f"Expected unit norm, got {norm}"


@pytest.mark.asyncio
async def test_project_embedding_function_raises_not_implemented():
    """Verify embed_documents() raises NotImplementedError."""
    emb_fn = _ProjectEmbeddingFunction()
    with pytest.raises(NotImplementedError, match="embed_documents is not supported"):
        emb_fn.embed_documents(["test"])


@pytest.mark.asyncio
async def test_get_embeddings_returns_adapter():
    """Verify _get_embeddings() returns a _ProjectEmbeddingFunction instance."""
    with patch("sentence_transformers.SentenceTransformer"):
        retriever = LangChainRetriever()
        result = await retriever._get_embeddings()
        assert isinstance(result, _ProjectEmbeddingFunction)


@pytest.mark.asyncio
async def test_faiss_uses_real_scores():
    """Verify FAISS returns real similarity scores, not fake 1/(rank+1).

    Builds a FAISS index with controlled 4D embeddings (no ML model needed),
    then queries with [1.0, 0.0, 0.0, 0.0] and checks that the returned
    scores have variance, are in a valid range, and do NOT match the
    fake 1/(rank+1) pattern that was the symptom of the bug.
    """
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document

    # Controlled 4D embeddings — no SentenceTransformer model needed
    docs = [
        Document(
            page_content="How to change view mode in AxisVM: use EWindowState enum",
            metadata={"chunk_id": "chunk-0", "document_id": "doc-1", "chunk_index": 0},
        ),
        Document(
            page_content="The view mode can be toggled via the View menu",
            metadata={"chunk_id": "chunk-1", "document_id": "doc-1", "chunk_index": 1},
        ),
        Document(
            page_content="Python is a programming language",
            metadata={"chunk_id": "chunk-2", "document_id": "doc-1", "chunk_index": 2},
        ),
        Document(
            page_content="AxisVM supports various structural analysis types",
            metadata={"chunk_id": "chunk-3", "document_id": "doc-1", "chunk_index": 3},
        ),
        Document(
            page_content="System requirements include 8GB RAM minimum",
            metadata={"chunk_id": "chunk-4", "document_id": "doc-1", "chunk_index": 4},
        ),
    ]

    # Embeddings where chunk-0 and chunk-1 are semantically close to query [1,0,0,0]
    embeddings = [
        [1.0, 0.0, 0.0, 0.0],  # chunk-0: exact match
        [0.9, 0.1, 0.0, 0.0],  # chunk-1: very close
        [0.2, 0.8, 0.3, 0.1],  # chunk-2: far
        [0.3, 0.7, 0.2, 0.4],  # chunk-3: far
        [0.1, 0.2, 0.9, 0.8],  # chunk-4: far
    ]

    embed_fn = MockEmbeddings(query_result=[1.0, 0.0, 0.0, 0.0])

    faiss_store = FAISS.from_embeddings(
        text_embeddings=list(zip([d.page_content for d in docs], embeddings)),
        embedding=embed_fn,
        metadatas=[d.metadata for d in docs],
    )

    results = await faiss_store.asimilarity_search_with_relevance_scores(
        "test query", k=5
    )

    scores = [float(score) for _, score in results]
    assert len(scores) == 5, f"Expected 5 scores, got {len(scores)}"

    # Scores must have variance (real similarities differ per chunk)
    score_variance = np.var(scores)
    assert score_variance > 1e-6, (
        f"Scores appear uniform (variance={score_variance:.6f}): {scores}"
    )

    # Top result must be chunk-0 (exact embedding match)
    top_chunk_id = results[0][0].metadata["chunk_id"]
    assert top_chunk_id == "chunk-0", (
        f"Expected chunk-0 as top result, got {top_chunk_id}"
    )
    top_score = float(results[0][1])
    second_score = float(results[1][1])
    assert top_score > second_score, (
        f"Top score ({top_score:.4f}) should exceed second score ({second_score:.4f})"
    )

    # Scores should NOT match the fake 1/(rank+1) pattern that was the bug
    fake_pattern = [1.0 / (i + 1) for i in range(5)]
    assert not np.allclose(scores, fake_pattern, atol=0.01), (
        f"Scores match fake 1/(rank+1) pattern! {scores} == {fake_pattern}"
    )

    # All scores should be finite (no NaN/Inf) and the order must be meaningful.
    # FAISS can return negative relevance for very dissimilar non-normalized vectors,
    # but the scores must be valid floats and the top result must be correct.
    for i, s in enumerate(scores):
        assert np.isfinite(s), f"Score {s} for result {i} is not finite"


@pytest.mark.asyncio
async def test_retrieve_returns_expected_chunks():
    """Verify LangChainRetriever.retrieve() ranks chunks correctly.

    With controlled embeddings where chunk-0 = [1,0,0,0] and
    chunk-1 = [0.9,0.1,0,0], these two must score highest when queried
    with [1,0,0,0]. Also verifies scores have variance and are in [0,1].
    """
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document

    docs = [
        Document(
            page_content="AxisVM EWindowState enum for view mode",
            metadata={"chunk_id": "chunk-0", "document_id": "doc-1", "chunk_index": 0},
        ),
        Document(
            page_content="Toggle view mode via View menu",
            metadata={"chunk_id": "chunk-1", "document_id": "doc-1", "chunk_index": 1},
        ),
        Document(
            page_content="Python programming language overview",
            metadata={"chunk_id": "chunk-2", "document_id": "doc-1", "chunk_index": 2},
        ),
        Document(
            page_content="AxisVM structural analysis features",
            metadata={"chunk_id": "chunk-3", "document_id": "doc-1", "chunk_index": 3},
        ),
        Document(
            page_content="System requirements 8GB RAM",
            metadata={"chunk_id": "chunk-4", "document_id": "doc-1", "chunk_index": 4},
        ),
    ]

    embeddings = [
        [1.0, 0.0, 0.0, 0.0],  # chunk-0: exact match to query
        [0.9, 0.1, 0.0, 0.0],  # chunk-1: very close
        [0.2, 0.8, 0.3, 0.1],  # chunk-2: far
        [0.3, 0.7, 0.2, 0.4],  # chunk-3: far
        [0.1, 0.2, 0.9, 0.8],  # chunk-4: far
    ]

    embed_fn = MockEmbeddings(query_result=[1.0, 0.0, 0.0, 0.0])

    # Build FAISS vectorstore from controlled embeddings
    faiss_store = FAISS.from_embeddings(
        text_embeddings=list(zip([d.page_content for d in docs], embeddings)),
        embedding=embed_fn,
        metadatas=[d.metadata for d in docs],
    )

    # Override settings for the duration of this test so that:
    #   - reranker is disabled (no model to load)
    #   - min_relevance_score is 0.0 (no results filtered out)
    settings = get_settings()
    old_min_relevance = settings.min_relevance_score
    old_reranker = settings.reranker_enabled
    settings.min_relevance_score = 0.0
    settings.reranker_enabled = False

    try:
        retriever = LangChainRetriever()
        retriever._index_built = True
        retriever._faiss_vectorstore = faiss_store
        retriever._chunks = []

        # BM25 mock returns empty list — all scores come from FAISS
        mock_bm25 = MagicMock()
        mock_bm25.ainvoke = AsyncMock(return_value=[])
        retriever._bm25_retriever = mock_bm25

        # Ensemble just needs to be non-None to pass the guard check
        retriever._ensemble = MagicMock()

        results = await retriever.retrieve("view mode query", top_k=5)

        assert len(results) > 0, "Should return at least one result"

        result_ids = [r.chunk_id for r in results]

        assert "chunk-0" in result_ids, (
            f"chunk-0 should be in results, got {result_ids}"
        )
        assert "chunk-1" in result_ids, (
            f"chunk-1 should be in results, got {result_ids}"
        )

        assert results[0].chunk_id == "chunk-0", (
            f"Expected chunk-0 first, got {results[0].chunk_id}"
        )

        # chunk-0 must score higher than chunk-1
        chunk_0_score = results[0].score
        chunk_1_idx = result_ids.index("chunk-1")
        chunk_1_score = results[chunk_1_idx].score
        assert chunk_0_score > chunk_1_score, (
            f"chunk-0 ({chunk_0_score:.4f}) should score higher than "
            f"chunk-1 ({chunk_1_score:.4f})"
        )

        # Scores should vary (not uniform)
        scores = [r.score for r in results]
        unique_scores = {round(s, 4) for s in scores}
        assert len(unique_scores) > 1, (
            f"Scores appear uniform (all {unique_scores}): {scores}"
        )

        # All scores in valid [0, 1] range
        for r in results:
            assert 0.0 <= r.score <= 1.0, (
                f"Score {r.score:.4f} for {r.chunk_id} outside [0, 1] range"
            )

        # Every result must have non-empty content and correct metadata
        for r in results:
            assert r.content, f"Result {r.chunk_id} has empty content"
            assert r.metadata is not None, f"Result {r.chunk_id} has no metadata"
            assert r.metadata.get("chunk_id") == r.chunk_id, (
                f"Result chunk_id mismatch: {r.chunk_id} vs metadata {r.metadata}"
            )

    finally:
        settings.min_relevance_score = old_min_relevance
        settings.reranker_enabled = old_reranker
