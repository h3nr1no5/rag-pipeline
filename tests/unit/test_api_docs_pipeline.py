"""Unit tests for DSPy pipeline: signatures, assertions, and metrics.

Task 9.5 — Tests the class definitions (signatures) and pure-Python
assertion/metric functions without requiring a running LM.
"""

from src.domain.rag.api_docs.pipeline.assertions import (
    check_question_references,
    validate_citations,
)
from src.domain.rag.api_docs.pipeline.metrics import (
    citation_accuracy,
    composite_score,
    hallucination_rate,
    retrieval_recall,
)
from src.domain.rag.api_docs.pipeline.signatures import (
    APIResponseGenerator,
    ContextAssembler,
    QueryAnalyzer,
)

# ---------------------------------------------------------------------------
# DSPy Signature definitions
# ---------------------------------------------------------------------------


class TestQueryAnalyzerSignature:
    """QueryAnalyzer signature has the expected input/output fields.

    DSPy signatures use a metaclass that stores fields in ``model_fields``.
    """

    def test_has_input_question(self):
        assert "question" in QueryAnalyzer.model_fields

    def test_has_output_search_queries(self):
        assert "search_queries" in QueryAnalyzer.model_fields

    def test_has_output_target_types(self):
        assert "target_types" in QueryAnalyzer.model_fields

    def test_has_output_intent(self):
        assert "intent" in QueryAnalyzer.model_fields


class TestContextAssemblerSignature:
    """ContextAssembler signature has the expected input/output fields."""

    def test_has_input_question(self):
        assert "question" in ContextAssembler.model_fields

    def test_has_input_chunks(self):
        assert "chunks" in ContextAssembler.model_fields

    def test_has_output_assembled_context(self):
        assert "assembled_context" in ContextAssembler.model_fields

    def test_has_output_primary_chunk_id(self):
        assert "primary_chunk_id" in ContextAssembler.model_fields


class TestAPIResponseGeneratorSignature:
    """APIResponseGenerator signature has the expected input/output fields."""

    def test_has_input_context(self):
        assert "context" in APIResponseGenerator.model_fields

    def test_has_input_question(self):
        assert "question" in APIResponseGenerator.model_fields

    def test_has_output_answer(self):
        assert "answer" in APIResponseGenerator.model_fields

    def test_has_output_citations(self):
        assert "citations" in APIResponseGenerator.model_fields

    def test_has_output_relevant_functions(self):
        assert "relevant_functions" in APIResponseGenerator.model_fields

    def test_has_output_relevant_types(self):
        assert "relevant_types" in APIResponseGenerator.model_fields

    def test_has_output_confidence(self):
        assert "confidence" in APIResponseGenerator.model_fields


# ---------------------------------------------------------------------------
# validate_citations
# ---------------------------------------------------------------------------


def test_validate_citations_all_valid():
    """All citations are in the known sets."""
    result = validate_citations(
        answer="Use the [CreateNode] function.",
        citations=["CreateNode"],
        available_functions={"CreateNode", "DeleteNode"},
        available_types={"INode"},
    )
    assert result["valid"] is True
    assert result["missing_inline_citations"] is False
    assert result["unknown_citations"] == []


def test_validate_citations_missing_inline():
    """Answer without [Name] citations fails validation."""
    result = validate_citations(
        answer="Use the CreateNode function.",
        citations=[],
        available_functions={"CreateNode"},
        available_types=set(),
    )
    assert result["valid"] is False
    assert result["missing_inline_citations"] is True


def test_validate_citations_unknown():
    """Citations not in the known sets are reported as unknown."""
    result = validate_citations(
        answer="Use the [FakeFunc] function.",
        citations=["FakeFunc"],
        available_functions={"RealFunc"},
        available_types=set(),
    )
    assert result["valid"] is False
    assert "FakeFunc" in result["unknown_citations"]


def test_validate_citations_empty_answer():
    """Empty answer produces no inline citations."""
    result = validate_citations(
        answer="",
        citations=[],
        available_functions={"Func"},
        available_types=set(),
    )
    assert result["valid"] is False
    assert result["missing_inline_citations"] is True


# ---------------------------------------------------------------------------
# check_question_references
# ---------------------------------------------------------------------------


def test_check_question_references_all_covered():
    """Function mentioned in question is referenced in answer."""
    result = check_question_references(
        question="How do I use CreateNode?",
        answer="The [CreateNode] method creates a node.",
        available_functions={"CreateNode"},
        available_types=set(),
    )
    assert result["valid"] is True


def test_check_question_references_missing():
    """Function mentioned in question but not in answer fails."""
    result = check_question_references(
        question="How do I use CreateNode?",
        answer="Use the DeleteNode method instead.",
        available_functions={"CreateNode", "DeleteNode"},
        available_types=set(),
    )
    assert result["valid"] is False
    assert "CreateNode" in result["mentioned_in_question"]
    assert "CreateNode" not in result["referenced_in_answer"]


def test_check_question_references_no_names():
    """Question with no known function/type names passes vacuously."""
    result = check_question_references(
        question="What is this API about?",
        answer="It is about nodes and elements.",
        available_functions=set(),
        available_types=set(),
    )
    assert result["valid"] is True


# ---------------------------------------------------------------------------
# retrieval_recall metric
# ---------------------------------------------------------------------------


class Example:
    """Minimal stand-in for dspy.Example."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class Prediction:
    """Minimal stand-in for prediction objects."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_retrieval_recall_perfect():
    """All gold items found in retrieved chunks."""
    example = Example(gold_functions=["CreateNode"], gold_types=["INode"])
    prediction = Prediction(
        retrieved_chunks=[("chunk_CreateNode", 0.9), ("chunk_INode", 0.8)]
    )
    # "chunk_CreateNode" contains "createnode" (lowercase)
    score = retrieval_recall(example, prediction)
    assert score > 0


def test_retrieval_recall_none():
    """No gold items found gives 0.0."""
    example = Example(gold_functions=["MissingFunc"], gold_types=[])
    prediction = Prediction(
        retrieved_chunks=[("chunk_Other", 0.9)]
    )
    score = retrieval_recall(example, prediction)
    assert score == 0.0


def test_retrieval_recall_no_gold():
    """No gold standard means perfect score (vacuously)."""
    example = Example(gold_functions=[], gold_types=[])
    prediction = Prediction(retrieved_chunks=[("chunk_1", 0.5)])
    assert retrieval_recall(example, prediction) == 1.0


def test_retrieval_recall_empty_retrieval():
    """No retrieved chunks gives 0.0."""
    example = Example(gold_functions=["Func"], gold_types=[])
    prediction = Prediction(retrieved_chunks=[])
    assert retrieval_recall(example, prediction) == 0.0


def test_retrieval_recall_dict_prediction():
    """Works with plain dict predictions."""
    example = Example(gold_functions=["CreateNode"], gold_types=[])
    prediction = {"retrieved_chunks": [("chunk_CreateNode", 0.9)]}
    score = retrieval_recall(example, prediction)
    assert score > 0


# ---------------------------------------------------------------------------
# citation_accuracy metric
# ---------------------------------------------------------------------------


def test_citation_accuracy_perfect():
    """All citations reference known functions/types."""
    example = Example(gold_functions=["CreateNode"], gold_types=["INode"])
    prediction = Prediction(
        answer="Use [CreateNode].",
        citations=["CreateNode", "INode"],
    )
    assert citation_accuracy(example, prediction) == 1.0


def test_citation_accuracy_partial():
    """Some citations are unknown."""
    example = Example(gold_functions=["CreateNode"], gold_types=[])
    prediction = Prediction(
        answer="Use [CreateNode] and [FakeFunc].",
        citations=[],
    )
    score = citation_accuracy(example, prediction)
    assert 0.0 < score < 1.0


def test_citation_accuracy_no_gold():
    """No gold standard means perfect score."""
    example = Example(gold_functions=[], gold_types=[])
    prediction = Prediction(answer="Some text.", citations=[])
    assert citation_accuracy(example, prediction) == 1.0


def test_citation_accuracy_no_citations():
    """No citations at all gives 0.0."""
    example = Example(gold_functions=["Func"], gold_types=[])
    prediction = Prediction(answer="Some text.", citations=[])
    assert citation_accuracy(example, prediction) == 0.0


# ---------------------------------------------------------------------------
# hallucination_rate metric
# ---------------------------------------------------------------------------


def test_hallucination_rate_none():
    """No hallucinations when all cited names are known."""
    example = Example(gold_functions=["CreateNode"], gold_types=["INode"])
    prediction = Prediction(
        answer="Use [CreateNode].",
        citations=["CreateNode", "INode"],
    )
    assert hallucination_rate(example, prediction) == 0.0


def test_hallucination_rate_all():
    """All citations are hallucinated."""
    example = Example(gold_functions=[], gold_types=[])
    prediction = Prediction(
        answer="Use [FakeFunc].",
        citations=["FakeFunc"],
    )
    assert hallucination_rate(example, prediction) == 1.0


def test_hallucination_rate_no_citations():
    """No citations means no hallucinations."""
    example = Example(gold_functions=["Func"], gold_types=[])
    prediction = Prediction(answer="Some text.", citations=[])
    assert hallucination_rate(example, prediction) == 0.0


# ---------------------------------------------------------------------------
# composite_score metric
# ---------------------------------------------------------------------------


def test_composite_score_perfect():
    """Perfect retrieval + citations + low hallucination = high score."""
    example = Example(gold_functions=["CreateNode"], gold_types=["INode"])
    prediction = Prediction(
        retrieved_chunks=[("chunk_CreateNode", 0.9), ("chunk_INode", 0.8)],
        answer="Use [CreateNode].",
        citations=["CreateNode", "INode"],
    )
    score = composite_score(example, prediction)
    assert score > 0.5
    assert score <= 1.0


def test_composite_score_bad():
    """Poor retrieval + bad citations + hallucination = low score."""
    example = Example(gold_functions=["RealFunc"], gold_types=[])
    prediction = Prediction(
        retrieved_chunks=[],
        answer="Use [FakeFunc].",
        citations=["FakeFunc"],
    )
    score = composite_score(example, prediction)
    assert score < 0.5
