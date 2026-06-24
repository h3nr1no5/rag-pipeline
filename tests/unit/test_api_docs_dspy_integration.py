"""Unit tests for DSPy integration in ApiDocPipelineManager.

Tests 5.1-5.4: DSPy-enabled path output mapping, circuit breaker fallback,
DSPy-disabled path skip, and chunk source resolution via graph.

All mocks target the *definition* path (where the class/function lives) because
the manager uses lazy imports inside method bodies (``from X import Y``), which
resolve against the original module at call time.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.domain.rag.api_docs.chunking.builder import ChunkGraph
from src.domain.rag.api_docs.chunking.graph import ChunkNode
from src.domain.rag.api_docs.manager import ApiDocPipelineManager
from src.domain.rag.api_docs.pipeline.schemas import ApiDocQueryResponse, ApiDocSource
from src.domain.rag.api_docs.retrieval.hybrid_retriever import HybridRetriever
from src.domain.services.verification import VerifiedResponse


# ===================================================================
# Test 5.1: DSPy-enabled path output mapping
# ===================================================================


@pytest.mark.asyncio
async def test_query_dspy_maps_output_correctly():
    """_query_dspy() correctly maps APIDocRAG.forward() output to ApiDocQueryResponse.

    Creates a real ChunkGraph with 2 nodes, mocks APIDocRAG to return a known
    dict, mocks ResponseVerifier.verify, and verifies every field of the result.
    """
    # --- Arrange ------------------------------------------------------------
    # Real ChunkGraph with 2 nodes (method + property)
    graph = ChunkGraph()
    graph.nodes["chunk_1"] = ChunkNode(
        chunk_id="chunk_1",
        kind="method",
        content="Method content",
        metadata={"interface_name": "IFoo", "function_name": "Bar"},
    )
    graph.nodes["chunk_2"] = ChunkNode(
        chunk_id="chunk_2",
        kind="property",
        content="Count property",
        metadata={"interface_name": "IFoo", "function_name": "Count"},
    )

    mock_retriever = MagicMock(spec=HybridRetriever)
    manager = ApiDocPipelineManager()

    # Dict that APIDocRAG.forward() would return
    forward_result = {
        "answer": "The answer from DSPy",
        "citations": ["chunk_1", "chunk_2"],
        "relevant_functions": ["Bar", "Count"],
        "relevant_types": ["IFoo"],
        "confidence": 0.85,
        "retrieved_chunks": [("chunk_1", 0.95), ("chunk_2", 0.85)],
        "primary_chunk_id": "chunk_1",
        "assertions_passed": True,
        "used_fallback": False,
    }

    # --- Act ----------------------------------------------------------------
    with patch(
        "src.domain.rag.api_docs.pipeline.module.APIDocRAG",
    ) as mock_apidoc_rag_class:
        mock_module = MagicMock()
        mock_module.forward.return_value = forward_result
        mock_apidoc_rag_class.return_value = mock_module

        with patch(
            "src.domain.services.verification.ResponseVerifier.verify",
            new_callable=AsyncMock,
        ) as mock_verify:
            mock_verify.return_value = VerifiedResponse(
                verified_text="Verified answer",
                citations=[],
                unsupported=[],
                confidence=1.0,
            )

            response = await manager._query_dspy(
                retriever=mock_retriever,
                graph=graph,
                query_text="test query",
                top_k=5,
            )

    # --- Assert -------------------------------------------------------------
    # APIDocRAG was constructed with the correct retriever
    mock_apidoc_rag_class.assert_called_once_with(hybrid_retriever=mock_retriever)
    # forward() called with the correct arguments
    mock_module.forward.assert_called_once_with(question="test query", top_k=5)

    # Response is the correct type
    assert isinstance(response, ApiDocQueryResponse)

    # Answer comes from the verification step
    assert response.answer == "Verified answer"

    # Sources are correctly resolved from the graph
    assert len(response.sources) == 2

    # Source 0: chunk_1
    assert response.sources[0].chunk_id == "chunk_1"
    assert response.sources[0].interface_name == "IFoo"
    assert response.sources[0].function_name == "Bar"
    assert response.sources[0].content == "Method content"
    assert response.sources[0].kind == "method"
    assert response.sources[0].score == 0.95

    # Source 1: chunk_2
    assert response.sources[1].chunk_id == "chunk_2"
    assert response.sources[1].interface_name == "IFoo"
    assert response.sources[1].function_name == "Count"
    assert response.sources[1].content == "Count property"
    assert response.sources[1].kind == "property"
    assert response.sources[1].score == 0.85

    # Citations match the mock data
    assert response.citations == ["chunk_1", "chunk_2"]

    # Confidence comes from APIDocRAG's output
    assert response.confidence == 0.85

    # Not cached (DSPy path never caches)
    assert response.cached is False

    # Latency is a non-negative integer
    assert isinstance(response.latency_ms, int)
    assert response.latency_ms >= 0


# ===================================================================
# Test 5.2: Circuit breaker — DSPy raises, fallback is used
# ===================================================================


@pytest.mark.asyncio
async def test_circuit_breaker_falls_back_when_dspy_fails():
    """query() falls back to _query_fallback when DSPy pipeline raises.

    We override ``_dspy_enabled = True`` because the test env sets it to
    ``False``.  We then patch APIDocRAG to raise, mock the fallback, and
    verify the fallback response is returned.
    """
    # --- Arrange ------------------------------------------------------------
    manager = ApiDocPipelineManager()
    manager._dspy_enabled = True  # override test env default

    # Build minimal real graph + mock retriever
    graph = ChunkGraph()
    graph.nodes["chunk_1"] = ChunkNode(
        chunk_id="chunk_1",
        kind="method",
        content="content",
        metadata={"interface_name": "IFoo", "function_name": "Bar"},
    )
    mock_retriever = MagicMock(spec=HybridRetriever)

    # Register the doc as indexed
    manager._indexed_docs[("", "test-doc")] = {
        "retriever": mock_retriever,
        "graph": graph,
    }

    # Mock the fallback on the instance (shadows the class method)
    fallback_response = ApiDocQueryResponse(
        answer="fallback answer",
        sources=[],
        latency_ms=0,
    )
    manager._query_fallback = AsyncMock(return_value=fallback_response)

    # --- Act ----------------------------------------------------------------
    with patch(
        "src.domain.rag.api_docs.pipeline.module.APIDocRAG",
    ) as mock_class:
        mock_instance = MagicMock()
        mock_instance.forward.side_effect = RuntimeError("DSPy failed")
        mock_class.return_value = mock_instance

        response = await manager.query("test-doc", "test query", top_k=3)

    # --- Assert -------------------------------------------------------------
    assert response.answer == "fallback answer"
    manager._query_fallback.assert_called_once()


# ===================================================================
# Test 5.3: DSPy disabled — DSPy path is skipped entirely
# ===================================================================


@pytest.mark.asyncio
async def test_dspy_disabled_skips_dspy_path():
    """query() skips the DSPy path entirely when ``_dspy_enabled`` is False.

    In the test environment ``API_DOCS_DSPY_ENABLED=false`` is set, so
    ``_dspy_enabled`` is ``False``.  We mock ``_query_fallback`` and spy on
    ``_query_dspy`` to confirm the latter is never called.
    """
    # --- Arrange ------------------------------------------------------------
    manager = ApiDocPipelineManager()
    assert manager._dspy_enabled is False, (
        "Test env should have DSPy disabled"
    )

    # Set up minimal indexed doc
    graph = ChunkGraph()
    graph.nodes["chunk_1"] = ChunkNode(
        chunk_id="chunk_1",
        kind="method",
        content="content",
        metadata={"interface_name": "IFoo", "function_name": "Bar"},
    )
    mock_retriever = MagicMock(spec=HybridRetriever)
    manager._indexed_docs[("", "test-doc")] = {
        "retriever": mock_retriever,
        "graph": graph,
    }

    # Mock fallback and spy on DSPy path
    fallback_response = ApiDocQueryResponse(
        answer="fallback answer",
        sources=[],
        latency_ms=0,
    )
    manager._query_fallback = AsyncMock(return_value=fallback_response)
    manager._query_dspy = AsyncMock()

    # --- Act ----------------------------------------------------------------
    response = await manager.query("test-doc", "test query")

    # --- Assert -------------------------------------------------------------
    # Fallback was called; DSPy path was never reached
    manager._query_fallback.assert_called_once()
    manager._query_dspy.assert_not_called()
    assert response.answer == "fallback answer"


# ===================================================================
# Test 5.4: Chunk resolution via graph
# ===================================================================


@pytest.mark.asyncio
async def test_resolve_chunk_sources_via_graph():
    """_resolve_chunk_sources() resolves (chunk_id, score) tuples correctly.

    Tests three scenarios:
      a. Normal resolution with 2 valid chunk IDs.
      b. Unknown chunk ID is silently skipped.
      c. Empty input produces an empty list.
      d. Node with empty metadata uses defaults.
    """
    # --- Arrange ------------------------------------------------------------
    graph = ChunkGraph()
    graph.nodes["chunk_a"] = ChunkNode(
        chunk_id="chunk_a",
        kind="method",
        content="Method A content",
        metadata={"interface_name": "IFoo", "function_name": "MethodA"},
    )
    graph.nodes["chunk_b"] = ChunkNode(
        chunk_id="chunk_b",
        kind="property",
        content="Property B content",
        metadata={"interface_name": "IFoo", "function_name": "PropB"},
    )
    graph.nodes["chunk_c"] = ChunkNode(
        chunk_id="chunk_c",
        kind="enum",
        content="Enum C content",
        metadata={},
    )

    manager = ApiDocPipelineManager()

    # --- Case a: Normal resolution ------------------------------------------
    sources = manager._resolve_chunk_sources(
        [("chunk_a", 0.95), ("chunk_b", 0.85)],
        graph,
    )
    assert len(sources) == 2

    # chunk_a
    assert sources[0].chunk_id == "chunk_a"
    assert sources[0].content == "Method A content"
    assert sources[0].score == 0.95
    assert sources[0].kind == "method"
    assert sources[0].interface_name == "IFoo"
    assert sources[0].function_name == "MethodA"

    # chunk_b
    assert sources[1].chunk_id == "chunk_b"
    assert sources[1].content == "Property B content"
    assert sources[1].score == 0.85
    assert sources[1].kind == "property"
    assert sources[1].interface_name == "IFoo"
    assert sources[1].function_name == "PropB"

    # --- Case b: Unknown chunk ID silently skipped -------------------------
    sources = manager._resolve_chunk_sources(
        [("chunk_a", 0.9), ("unknown_chunk", 0.5)],
        graph,
    )
    assert len(sources) == 1
    assert sources[0].chunk_id == "chunk_a"

    # --- Case c: Empty input -> empty output -------------------------------
    sources = manager._resolve_chunk_sources([], graph)
    assert len(sources) == 0

    # --- Case d: Node with empty metadata ----------------------------------
    sources = manager._resolve_chunk_sources(
        [("chunk_c", 0.7)],
        graph,
    )
    assert len(sources) == 1
    assert sources[0].chunk_id == "chunk_c"
    assert sources[0].content == "Enum C content"
    assert sources[0].function_name == ""  # empty metadata
    assert sources[0].interface_name == ""  # empty metadata
