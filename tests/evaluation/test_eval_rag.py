"""Smoke tests for the RAG evaluation module.

Tests cover:
  1. Module imports — all public symbols load without errors.
  2. Dataset loading — load, validate, error handling.
  3. Metric computation — each metric with synthetic data.
"""

import json

import pytest

from src.evaluation.dataset import EvalDataset, load_dataset
from src.evaluation.metrics import (
    faithfulness,
    keyword_recall,
    mrr,
    precision_at_k,
    recall_at_k,
)
from src.evaluation.report import (
    write_json_report,
    write_markdown_report,
)

# ---------------------------------------------------------------------------
# 1.  Module imports
# ---------------------------------------------------------------------------

class TestModuleImports:
    """All evaluation module symbols should be importable."""

    def test_all_imports_resolve(self):
        """Verify every expected symbol is importable and not None."""
        assert load_dataset is not None
        assert EvalDataset is not None
        assert precision_at_k is not None
        assert recall_at_k is not None
        assert mrr is not None
        assert keyword_recall is not None
        assert faithfulness is not None
        assert write_json_report is not None
        assert write_markdown_report is not None


# ---------------------------------------------------------------------------
# 2.  Dataset loading
# ---------------------------------------------------------------------------

class TestDatasetLoads:
    """Verify dataset loading, field parsing, and validation errors."""

    def test_load_minimal_dataset(self, tmp_path):
        """Load a minimal inline dataset and verify all parsed fields."""
        # Create a document file referenced by the dataset
        doc_file = tmp_path / "doc1.txt"
        doc_file.write_text("Python is a high-level programming language.")

        dataset_file = tmp_path / "dataset.json"
        dataset_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "created": "2024-01-01",
                    "description": "Smoke-test dataset",
                    "documents": [
                        {"filename": "doc1.txt", "path": str(doc_file)},
                    ],
                    "questions": [
                        {
                            "id": "q1",
                            "question": "What is Python?",
                            "document": "doc1.txt",
                            "expected_sources": [
                                "Python is a high-level programming language.",
                            ],
                            "expected_keywords": ["Python", "programming"],
                        },
                    ],
                },
            ),
        )

        dataset = load_dataset(str(dataset_file))

        # Version field
        assert dataset.version == "1.0"

        # At least one question
        assert len(dataset.questions) == 1
        q = dataset.questions[0]
        assert q.id == "q1"
        assert q.question == "What is Python?"
        assert q.document == "doc1.txt"
        assert "Python" in q.expected_keywords

        # Documents properly parsed
        assert len(dataset.documents) == 1
        assert dataset.documents[0].filename == "doc1.txt"
        assert dataset.documents[0].path == str(doc_file)

    def test_file_not_found(self):
        """Non-existent dataset path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_dataset("/nonexistent/path/eval_dataset.json")

    def test_missing_version_field(self, tmp_path):
        """Dataset without 'version' field raises ValueError."""
        dataset_file = tmp_path / "no_version.json"
        dataset_file.write_text(
            json.dumps(
                {
                    "created": "2024-01-01",
                    "description": "Missing version",
                    "documents": [],
                    "questions": [
                        {
                            "id": "q1",
                            "question": "What is Python?",
                            "document": "",
                            "expected_sources": [],
                            "expected_keywords": [],
                        },
                    ],
                },
            ),
        )

        with pytest.raises(ValueError, match="version"):
            load_dataset(str(dataset_file))

    def test_missing_question(self, tmp_path):
        """Dataset with no questions raises ValueError."""
        dataset_file = tmp_path / "no_questions.json"
        dataset_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "created": "2024-01-01",
                    "description": "No questions",
                    "documents": [],
                    "questions": [],
                },
            ),
        )

        with pytest.raises(ValueError, match="question"):
            load_dataset(str(dataset_file))


# ---------------------------------------------------------------------------
# 3.  Metric computation
# ---------------------------------------------------------------------------

class TestMetricsCompute:
    """Synthetic-data assertions for each metric function."""

    # -- precision_at_k ------------------------------------------------------

    def test_precision_at_k_standard(self):
        """1 relevant among 3 retrieved → 1/3."""
        assert precision_at_k(relevant={"a"}, retrieved=["a", "b", "c"], k=3) == pytest.approx(
            1 / 3,
        )

    def test_precision_at_k_top1(self):
        """Relevant result at rank 1, k=1 → 1.0."""
        assert precision_at_k(relevant={"a"}, retrieved=["a", "b", "c"], k=1) == 1.0

    # -- recall_at_k --------------------------------------------------------

    def test_recall_at_k_partial(self):
        """2 relevant, 1 retrieved → 0.5."""
        assert recall_at_k(relevant={"a", "b"}, retrieved=["a", "c"], k=3) == 0.5

    def test_recall_at_k_empty_retrieved(self):
        """Empty retrieved list → 0.0."""
        assert recall_at_k(relevant={"a", "b"}, retrieved=[], k=3) == 0.0

    # -- mrr ----------------------------------------------------------------

    def test_mrr_found(self):
        """Relevant at rank 2 → 0.5."""
        assert mrr(relevant={"b"}, retrieved=["a", "b", "c"]) == 0.5

    def test_mrr_not_found(self):
        """No relevant result → 0.0."""
        assert mrr(relevant={"x"}, retrieved=["a", "b", "c"]) == 0.0

    # -- keyword_recall -----------------------------------------------------

    def test_keyword_recall_partial(self):
        """1 of 2 keywords found → 0.5."""
        assert (
            keyword_recall(
                "Python is a programming language",
                ["programming language", "interpreted"],
            )
            == 0.5
        )

    def test_keyword_recall_empty_answer(self):
        """Empty answer → 0.0."""
        assert keyword_recall("", ["programming"]) == 0.0

    def test_keyword_recall_no_keywords(self):
        """No expected keywords → 1.0 (vacuously true)."""
        assert keyword_recall("Python is great", []) == 1.0
