"""Unit tests for APIDocRAG advisory assertion behavior.

Task 7.1: Verify that ``_generate_with_assertions()`` treats citation and
reference assertions as advisory — logging warnings but returning the original
ChainOfThought output instead of falling back to ``Predict``.

Previously, assertion failures triggered a fallback to ``_generate_fallback()``
(plain ``Predict``). After the "fix-api-docs-answer-quality" change, the CoT
output is always returned regardless of assertion results. Only a true runtime
exception from ``response_generator`` still triggers the fallback path.
"""

import logging

import pytest
from unittest.mock import MagicMock, PropertyMock, patch

from src.domain.rag.api_docs.pipeline.module import APIDocRAG


# ===================================================================
# Helper: create a mock response object that mimics DSPy output
# ===================================================================


def _make_mock_response(
    answer: str = "The [CreateNode] method creates a new node.",
    citations: str = "CreateNode",
    relevant_functions: str = "CreateNode",
    relevant_types: str = "INode",
    confidence: str = "0.85",
    rationale: str = "The user wants to create a new node, so I should look for CreateNode.",
):
    """Build a mock DSPy Prediction-like object with stripped-string attributes."""
    obj = MagicMock()
    obj.answer = answer
    obj.citations = citations
    obj.relevant_functions = relevant_functions
    obj.relevant_types = relevant_types
    obj.confidence = confidence
    obj.rationale = rationale
    return obj


# ===================================================================
# Fixture: APIDocRAG instance with mocked predictors
# ===================================================================


@pytest.fixture
def module():
    """Return an APIDocRAG instance whose inner predictors are all mocked.

    We cannot instantiate APIDocRAG with real DSPy predictors (no LM is
    configured in the test environment), so we patch ``dspy.ChainOfThought``
    and ``dspy.Predict`` to return plain ``MagicMock`` instances.
    """
    with patch("src.domain.rag.api_docs.pipeline.module.dspy.ChainOfThought") as mock_cot_cls, \
         patch("src.domain.rag.api_docs.pipeline.module.dspy.Predict") as mock_predict_cls:
        mock_cot_cls.return_value = MagicMock()
        mock_predict_cls.return_value = MagicMock()
        # The retriever is only used during forward(), not in
        # _generate_with_assertions(), so a simple mock suffices.
        retriever = MagicMock()
        m = APIDocRAG(hybrid_retriever=retriever)

        # Give each predictor a default mock-return so tests don't fail
        # if they accidentally call forward().  Individual tests override
        # this on the necessary predictor.
        m.response_generator = MagicMock()
        m.fallback_generator = MagicMock()

        return m


# ===================================================================
# Test: assertions pass
# ===================================================================


class TestGenerateWithAssertions:
    """Tests for ``APIDocRAG._generate_with_assertions()``."""

    def test_assertions_pass_returns_co_output(self, module):
        """When both citation and reference assertions pass, return CoT output."""
        # Arrange
        mock_resp = _make_mock_response()
        module.response_generator.return_value = mock_resp

        # Act
        result = module._generate_with_assertions(
            question="How do I create a node?",
            context="[CreateNode]\nCreates a node.\n\n[DeleteNode]\nDeletes a node.",
            available_functions={"CreateNode", "DeleteNode"},
            available_types={"INode"},
        )

        # Assert
        assert result["answer"] == "The [CreateNode] method creates a new node."
        assert result["citations"] == ["CreateNode"]
        assert result["relevant_functions"] == ["CreateNode"]
        assert result["relevant_types"] == ["INode"]
        assert result["confidence"] == 0.85
        assert result["assertions_passed"] is True
        assert result["used_fallback"] is False

    # ===============================================================
    # Test: rationale key is included in the return dict
    # ===============================================================

    def test_rationale_included_in_return_dict(self, module):
        """The return dict contains a ``rationale`` key with a non-empty string."""
        # Arrange
        expected_rationale = (
            "The user wants to create a new node, so I should look for CreateNode."
        )
        mock_resp = _make_mock_response(rationale=expected_rationale)
        module.response_generator.return_value = mock_resp

        # Act
        result = module._generate_with_assertions(
            question="How do I create a node?",
            context="[CreateNode]\nCreates a node.\n\n[DeleteNode]\nDeletes a node.",
            available_functions={"CreateNode", "DeleteNode"},
            available_types={"INode"},
        )

        # Assert
        assert "rationale" in result, "rationale key must be present in the result dict"
        assert isinstance(result["rationale"], str), "rationale must be a string"
        assert result["rationale"] == expected_rationale, (
            f"Expected rationale {expected_rationale!r}, got {result['rationale']!r}"
        )
        assert len(result["rationale"]) > 0, "rationale must be a non-empty string"
        # Ensure existing fields are still present and correct
        assert result["answer"] == "The [CreateNode] method creates a new node."
        assert result["citations"] == ["CreateNode"]
        assert result["relevant_functions"] == ["CreateNode"]
        assert result["relevant_types"] == ["INode"]
        assert result["confidence"] == 0.85
        assert result["assertions_passed"] is True
        assert result["used_fallback"] is False

    # ===============================================================
    # Test: assertions fail — advisory behavior
    # ===============================================================

    def test_assertions_fail_logs_warning_and_returns_co_output(self, module, caplog):
        """When assertions fail, a warning is logged and CoT output is returned.

        This is the core advisory behavior: the CoT output is accepted even
        though citations/references are imperfect.
        """
        # Arrange
        mock_resp = _make_mock_response(
            answer="Use the CreateNode method.",  # no [bracket] citations
            citations="",
            relevant_functions="CreateNode",
            relevant_types="",
            confidence="0.7",
        )
        module.response_generator.return_value = mock_resp

        caplog.set_level(logging.WARNING)

        # Act
        result = module._generate_with_assertions(
            question="How do I create a node?",
            context="[CreateNode]\nCreates a node.",
            available_functions={"CreateNode"},
            available_types=set(),
        )

        # Assert
        # 1. Warning was logged
        assert any(
            "DSPy assertion failed" in record.message
            for record in caplog.records
        ), "Expected warning log about assertion failure"

        # 2. CoT output is returned despite failed assertions
        assert result["answer"] == "Use the CreateNode method."
        assert result["assertions_passed"] is False
        assert result["used_fallback"] is False

    # ===============================================================
    # Test: assertions fail — fallback NOT called
    # ===============================================================

    def test_assertions_fail_does_not_call_fallback(self, module, caplog):
        """``_generate_fallback()`` is NOT called when assertions fail.

        Verify the method returns the original CoT answer directly without
        invoking the Predict-based fallback.
        """
        # Arrange
        mock_resp = _make_mock_response(
            answer="Use the CreateNode method.",  # no inline citations
            citations="",
            relevant_functions="CreateNode",
            relevant_types="",
            confidence="0.7",
        )
        module.response_generator.return_value = mock_resp

        # Spy on fallback
        module._generate_fallback = MagicMock()

        caplog.set_level(logging.WARNING)

        # Act
        result = module._generate_with_assertions(
            question="How do I create a node?",
            context="[CreateNode]\nCreates a node.",
            available_functions={"CreateNode"},
            available_types=set(),
        )

        # Assert
        module._generate_fallback.assert_not_called()
        assert result["answer"] == "Use the CreateNode method."
        assert result["assertions_passed"] is False

    # ===============================================================
    # Test: runtime exception still falls back
    # ===============================================================

    def test_runtime_exception_still_falls_back(self, module):
        """When ``response_generator`` raises, ``_generate_fallback()`` IS called.

        This is distinct from assertion failure — a true runtime error should
        still trigger the Predict fallback.
        """
        # Arrange
        module.response_generator.side_effect = RuntimeError("LM unavailable")
        fallback_result = {
            "answer": "Fallback answer.",
            "citations": [],
            "relevant_functions": [],
            "relevant_types": [],
            "confidence": 0.0,
            "assertions_passed": False,
            "used_fallback": True,
        }
        module._generate_fallback = MagicMock(return_value=fallback_result)

        # Act
        result = module._generate_with_assertions(
            question="How do I create a node?",
            context="[CreateNode]\nCreates a node.",
            available_functions={"CreateNode"},
            available_types=set(),
        )

        # Assert
        module._generate_fallback.assert_called_once()
        assert result["answer"] == "Fallback answer."
        assert result["used_fallback"] is True

    # ===============================================================
    # Test: assertion failure metadata in response
    # ===============================================================

    def test_assertions_fail_reports_both_citation_and_reference_issues(self, module, caplog):
        """When multiple assertions fail, all issues are logged in the warning."""
        # Arrange — answer mentions nothing from the retrieved context
        mock_resp = _make_mock_response(
            answer="I don't know the answer.",     # no inline citations
            citations="",                           # no explicit citations
            relevant_functions="",                  # claims no functions
            relevant_types="",
            confidence="0.1",
        )
        module.response_generator.return_value = mock_resp

        caplog.set_level(logging.WARNING)

        # Act
        result = module._generate_with_assertions(
            question="How do I use CreateNode?",
            context="[CreateNode]\nCreates a node.",
            available_functions={"CreateNode"},
            available_types=set(),
        )

        # Assert
        assert result["assertions_passed"] is False
        assert result["used_fallback"] is False

        # The log message should contain details from both assertion types
        warning_messages = [
            r.message for r in caplog.records
            if "DSPy assertion failed" in r.message
        ]
        assert len(warning_messages) == 1, "Expected exactly one assertion warning"
        msg = warning_messages[0]
        assert "citations" in msg, "Warning should include citation details"
        assert "refs" in msg, "Warning should include reference details"

    # ===============================================================
    # Test: assertions fail — rationale still present
    # ===============================================================

    def test_assertions_fail_still_includes_rationale(self, module):
        """When assertions fail, rationale is still included in the CoT output."""
        # Arrange
        mock_resp = _make_mock_response(
            answer="Use the CreateNode method.",
            citations="",
            relevant_functions="CreateNode",
            relevant_types="",
            confidence="0.7",
            rationale="The user asked about creating a node, so I should reference CreateNode.",
        )
        module.response_generator.return_value = mock_resp

        # Act
        result = module._generate_with_assertions(
            question="How do I create a node?",
            context="[CreateNode]\nCreates a node.",
            available_functions={"CreateNode"},
            available_types=set(),
        )

        # Assert
        assert "rationale" in result
        assert result["rationale"] == "The user asked about creating a node, so I should reference CreateNode."
        assert result["assertions_passed"] is False
        assert result["used_fallback"] is False

    # ===============================================================
    # Test: fallback path returns empty rationale
    # ===============================================================

    def test_fallback_path_returns_empty_rationale(self, module):
        """When runtime exception triggers fallback, rationale is empty string."""
        # Arrange
        module.response_generator.side_effect = RuntimeError("LM unavailable")
        fallback_result = {
            "answer": "Fallback answer.",
            "rationale": "",
            "citations": [],
            "relevant_functions": [],
            "relevant_types": [],
            "confidence": 0.0,
            "assertions_passed": False,
            "used_fallback": True,
        }
        module._generate_fallback = MagicMock(return_value=fallback_result)

        # Act
        result = module._generate_with_assertions(
            question="How do I create a node?",
            context="[CreateNode]\nCreates a node.",
            available_functions={"CreateNode"},
            available_types=set(),
        )

        # Assert
        assert "rationale" in result
        assert result["rationale"] == ""
        assert result["used_fallback"] is True
