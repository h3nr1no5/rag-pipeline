"""Unit tests for the new async DSPy pipeline methods.

Covers:

1. ``MLXDspyLM.aforward()`` — returns the correct ``SimpleNamespace`` shape.
2. ``APIDocRAG.aforward()`` — async entry point mirrors ``forward()`` output.
3. ``APIDocRAG._aforward_impl()`` — async retrieval + generation bridge.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.rag.api_docs.chunking.builder import ChunkGraph
from src.domain.rag.api_docs.chunking.graph import ChunkNode
from src.domain.rag.api_docs.retrieval.hybrid_retriever import HybridRetriever

# ===================================================================
# MLXDspyLM.aforward()
# ===================================================================


class TestMLXDspyLMForward:
    """MLXDspyLM.aforward() returns the expected response shape."""

    @pytest.mark.asyncio
    async def test_aforward_returns_namespace_with_choices(self):
        """aforward() returns a SimpleNamespace with choices[0].message.content."""
        # Mock the _llm_instance module-level variable so MLXDspyLM.__init__
        # picks up a mock instead of creating a real MLXLLM.
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="This is a test response.")

        with patch(
            "src.domain.rag.api_docs.pipeline.lm_adapter.get_settings",
        ) as mock_settings_fn:
            mock_settings_fn.return_value.llm_model = "test-model"
            mock_settings_fn.return_value.llm_temperature = 0.1
            mock_settings_fn.return_value.llm_max_tokens = 600
            mock_settings_fn.return_value.llm_repetition_penalty = 1.0

            with patch(
                "src.domain.rag.api_docs.pipeline.lm_adapter._llm_instance",
                mock_llm,
            ):
                # Avoid circular import — import after patches
                from src.domain.rag.api_docs.pipeline.lm_adapter import (
                    MLXDspyLM,
                )

                lm = MLXDspyLM()
                result = await lm.aforward(
                    prompt="What is the answer?",
                    temperature=0.2,
                )

        # The result should be a SimpleNamespace (OpenAI-compat format)
        assert isinstance(result, SimpleNamespace)
        assert hasattr(result, "choices")
        assert len(result.choices) == 1
        assert result.choices[0].message.content == "This is a test response."
        assert result.model == "test-model"

    @pytest.mark.asyncio
    async def test_aforward_with_messages(self):
        """aforward() handles message lists correctly."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="Test from messages.")

        with patch(
            "src.domain.rag.api_docs.pipeline.lm_adapter.get_settings",
        ) as mock_settings_fn:
            mock_settings_fn.return_value.llm_model = "test-model"
            mock_settings_fn.return_value.llm_temperature = 0.1
            mock_settings_fn.return_value.llm_max_tokens = 600
            mock_settings_fn.return_value.llm_repetition_penalty = 1.0

            with patch(
                "src.domain.rag.api_docs.pipeline.lm_adapter._llm_instance",
                mock_llm,
            ):
                from src.domain.rag.api_docs.pipeline.lm_adapter import (
                    MLXDspyLM,
                )

                lm = MLXDspyLM()
                result = await lm.aforward(
                    messages=[
                        {"role": "user", "content": "Hello"},
                        {"role": "assistant", "content": "Hi there"},
                    ],
                )

        assert isinstance(result, SimpleNamespace)
        assert result.choices[0].message.content == "Test from messages."

    @pytest.mark.asyncio
    async def test_aforward_raises_on_no_input(self):
        """aforward() raises ValueError when neither prompt nor messages given."""
        mock_llm = AsyncMock()
        # generate doesn't matter here — we won't reach it

        with patch(
            "src.domain.rag.api_docs.pipeline.lm_adapter.get_settings",
        ) as mock_settings_fn:
            mock_settings_fn.return_value.llm_model = "test-model"
            mock_settings_fn.return_value.llm_temperature = 0.1
            mock_settings_fn.return_value.llm_max_tokens = 600
            mock_settings_fn.return_value.llm_repetition_penalty = 1.0

            with patch(
                "src.domain.rag.api_docs.pipeline.lm_adapter._llm_instance",
                mock_llm,
            ):
                from src.domain.rag.api_docs.pipeline.lm_adapter import (
                    MLXDspyLM,
                )

                lm = MLXDspyLM()
                with pytest.raises(ValueError, match=r"Either.*prompt.*messages"):
                    await lm.aforward()


# ===================================================================
# APIDocRAG._aforward_impl()
# ===================================================================


class TestAPIDocRAGAforwardImpl:
    """_aforward_impl() performs async retrieval and returns expected dict."""

    @pytest.mark.asyncio
    async def test_aforward_impl_returns_expected_dict(self):
        """_aforward_impl() returns dict with all required keys."""
        # Build a real ChunkGraph with 2 nodes
        graph = _build_minimal_graph()

        # Mock the HybridRetriever so it returns known results
        mock_retriever = MagicMock(spec=HybridRetriever)
        mock_retriever.retrieve = AsyncMock(
            return_value=[
                (graph.nodes["chunk_a"], 0.95),
                (graph.nodes["chunk_b"], 0.85),
            ]
        )

        # Create the module (import lazily to avoid early DSPy configure)
        from src.domain.rag.api_docs.pipeline.module import APIDocRAG

        module = APIDocRAG(hybrid_retriever=mock_retriever)

        # Mock _generate_with_assertions as it's sync and uses DSPy predictors
        module._generate_with_assertions = MagicMock(
            return_value={
                "answer": "Use the CreateNode function.",
                "rationale": "The answer was found in chunk_a.",
                "citations": ["chunk_a"],
                "relevant_functions": ["CreateNode"],
                "relevant_types": ["IFoo"],
                "confidence": 0.9,
                "assertions_passed": True,
                "used_fallback": False,
            }
        )

        # Act
        result = await module._aforward_impl(
            question="How to create a node?", top_k=5
        )

        # Assert result structure
        assert isinstance(result, dict)
        assert result["answer"] == "Use the CreateNode function."
        assert result["rationale"] == "The answer was found in chunk_a."
        assert result["citations"] == ["chunk_a"]
        assert result["relevant_functions"] == ["CreateNode"]
        assert result["relevant_types"] == ["IFoo"]
        assert result["confidence"] == 0.9
        assert result["primary_chunk_id"] == "chunk_a"
        assert isinstance(result["retrieved_chunks"], list)
        assert len(result["retrieved_chunks"]) == 2
        assert result["retrieved_chunks"][0] == ("chunk_a", 0.95)
        assert result["assertions_passed"] is True
        assert result["used_fallback"] is False

        # Verify retriever was called asynchronously
        mock_retriever.retrieve.assert_awaited_once_with(
            "How to create a node?", top_k=5
        )

    @pytest.mark.asyncio
    async def test_aforward_impl_empty_retrieval(self):
        """_aforward_impl() returns a fallback dict when no chunks retrieved."""
        mock_retriever = MagicMock(spec=HybridRetriever)
        mock_retriever.retrieve = AsyncMock(return_value=[])

        from src.domain.rag.api_docs.pipeline.module import APIDocRAG

        module = APIDocRAG(hybrid_retriever=mock_retriever)

        result = await module._aforward_impl(question="Nothing here?", top_k=5)

        assert result["answer"] == (
            "I could not find relevant information in the API documentation."
        )
        assert result["citations"] == []
        assert result["confidence"] == 0.0
        assert result["assertions_passed"] is False
        assert result["used_fallback"] is False

    @pytest.mark.asyncio
    async def test_aforward_impl_retrieval_failure(self):
        """_aforward_impl() handles retrieval exceptions gracefully and returns
        fallback when no chunks succeed."""
        mock_retriever = MagicMock(spec=HybridRetriever)
        mock_retriever.retrieve = AsyncMock(
            side_effect=TimeoutError("retrieval timeout")
        )

        from src.domain.rag.api_docs.pipeline.module import APIDocRAG

        module = APIDocRAG(hybrid_retriever=mock_retriever)

        result = await module._aforward_impl(question="Error case?", top_k=5)

        assert result["answer"] == (
            "I could not find relevant information in the API documentation."
        )
        assert result["citations"] == []


# ===================================================================
# APIDocRAG.aforward()
# ===================================================================


class TestAPIDocRAGAforward:
    """aforward() async entry point mirrors forward() output."""

    @pytest.mark.asyncio
    async def test_aforward_validates_empty_question(self):
        """aforward() raises ValueError for empty/stripped questions."""
        mock_retriever = MagicMock(spec=HybridRetriever)

        from src.domain.rag.api_docs.pipeline.module import APIDocRAG

        module = APIDocRAG(hybrid_retriever=mock_retriever)

        with pytest.raises(ValueError, match="question cannot be empty"):
            await module.aforward(question="")

        with pytest.raises(ValueError, match="question cannot be empty"):
            await module.aforward(question="   ")

    @pytest.mark.asyncio
    async def test_aforward_validates_long_question(self):
        """aforward() raises ValueError for overly long questions."""
        mock_retriever = MagicMock(spec=HybridRetriever)

        from src.domain.rag.api_docs.pipeline.module import APIDocRAG

        module = APIDocRAG(hybrid_retriever=mock_retriever)

        with pytest.raises(ValueError, match="question too long"):
            await module.aforward(question="x" * 2001)

    @pytest.mark.asyncio
    async def test_aforward_delegates_to_aforward_impl(self):
        """aforward() delegates to _aforward_impl() and returns its result.

        When ``dspy.settings.lm`` is ``None`` (common in test environments),
        the temperature/max_tokens override blocks are skipped and the
        method still works correctly.
        """
        graph = _build_minimal_graph()
        mock_retriever = MagicMock(spec=HybridRetriever)
        mock_retriever.retrieve = AsyncMock(
            return_value=[
                (graph.nodes["chunk_a"], 0.95),
                (graph.nodes["chunk_b"], 0.85),
            ]
        )

        from src.domain.rag.api_docs.pipeline.module import APIDocRAG

        module = APIDocRAG(hybrid_retriever=mock_retriever)

        # Mock the generation step
        module._generate_with_assertions = MagicMock(
            return_value={
                "answer": "Use CreateNode from IFoo.",
                "rationale": "Found in chunk_a.",
                "citations": ["chunk_a"],
                "relevant_functions": ["CreateNode"],
                "relevant_types": ["IFoo"],
                "confidence": 0.92,
                "assertions_passed": True,
                "used_fallback": False,
            }
        )

        result = await module.aforward(
            question="How do I create a node?",
            top_k=5,
        )

        assert isinstance(result, dict)
        assert result["answer"] == "Use CreateNode from IFoo."
        assert result["rationale"] == "Found in chunk_a."
        assert result["citations"] == ["chunk_a"]
        assert result["relevant_functions"] == ["CreateNode"]
        assert result["relevant_types"] == ["IFoo"]
        assert result["confidence"] == 0.92
        assert result["primary_chunk_id"] == "chunk_a"
        assert len(result["retrieved_chunks"]) == 2
        assert result["assertions_passed"] is True
        assert result["used_fallback"] is False

    @pytest.mark.asyncio
    async def test_aforward_passes_top_k_to_impl(self):
        """aforward() passes top_k to _aforward_impl()."""
        mock_retriever = MagicMock(spec=HybridRetriever)

        from src.domain.rag.api_docs.pipeline.module import APIDocRAG

        module = APIDocRAG(hybrid_retriever=mock_retriever)
        module._aforward_impl = AsyncMock(
            return_value={
                "answer": "test",
                "rationale": "",
                "citations": [],
                "relevant_functions": [],
                "relevant_types": [],
                "confidence": 0.0,
                "primary_chunk_id": "",
                "retrieved_chunks": [],
                "assertions_passed": False,
                "used_fallback": False,
            }
        )

        await module.aforward(question="test?", top_k=3)
        module._aforward_impl.assert_awaited_once_with("test?", 3)


# ===================================================================
# Helpers
# ===================================================================


def _build_minimal_graph() -> ChunkGraph:
    """Build a two-node ChunkGraph for testing."""
    graph = ChunkGraph()
    graph.nodes["chunk_a"] = ChunkNode(
        chunk_id="chunk_a",
        kind="method",
        content="CreateNode creates a new node in the interface.",
        metadata={"interface_name": "IFoo", "function_name": "CreateNode"},
    )
    graph.nodes["chunk_b"] = ChunkNode(
        chunk_id="chunk_b",
        kind="property",
        content="Count property of IFoo.",
        metadata={"interface_name": "IFoo", "function_name": "Count"},
    )
    return graph
