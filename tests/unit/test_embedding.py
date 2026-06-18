"""Unit tests for embedding validation."""

import math
import pytest
from src.domain.services.embedding import validate_embedding


def test_validate_valid_embedding():
    """A list of floats with matching dimension returns (True, "")."""
    embedding = [0.1, 0.2, 0.3, 0.4]
    is_valid, reason = validate_embedding(embedding, expected_dim=4)
    assert is_valid is True
    assert reason == ""


def test_validate_valid_tuple():
    """A tuple of floats with matching dimension returns (True, "")."""
    embedding = (0.1, 0.2, 0.3)
    is_valid, reason = validate_embedding(embedding, expected_dim=3)
    assert is_valid is True
    assert reason == ""


def test_validate_none():
    """None returns (False, "embedding is None")."""
    is_valid, reason = validate_embedding(None, expected_dim=4)
    assert is_valid is False
    assert reason == "embedding is None"


def test_validate_non_list_type():
    """A string or int returns (False, ...) with type info."""
    # String
    is_valid, reason = validate_embedding("not-a-list", expected_dim=4)
    assert is_valid is False
    assert "embedding type is str, expected list or tuple" in reason

    # Integer
    is_valid, reason = validate_embedding(42, expected_dim=4)
    assert is_valid is False
    assert "embedding type is int, expected list or tuple" in reason

    # Float
    is_valid, reason = validate_embedding(3.14, expected_dim=4)
    assert is_valid is False
    assert "embedding type is float, expected list or tuple" in reason

    # Dict
    is_valid, reason = validate_embedding({"a": 1.0}, expected_dim=4)
    assert is_valid is False
    assert "embedding type is dict, expected list or tuple" in reason


def test_validate_dimension_mismatch():
    """A list with wrong length returns (False, "embedding dimension ... does not match ...")."""

    # Too short
    embedding = [0.1, 0.2]
    is_valid, reason = validate_embedding(embedding, expected_dim=4)
    assert is_valid is False
    assert reason == "embedding dimension 2 does not match expected dimension 4"

    # Too long
    embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
    is_valid, reason = validate_embedding(embedding, expected_dim=4)
    assert is_valid is False
    assert reason == "embedding dimension 5 does not match expected dimension 4"


def test_validate_nan_value():
    """A list containing float('nan') returns (False, "embedding contains NaN or non-numeric values")."""
    embedding = [0.1, 0.2, float("nan"), 0.4]
    is_valid, reason = validate_embedding(embedding, expected_dim=4)
    assert is_valid is False
    assert reason == "embedding contains NaN or non-numeric values"


def test_validate_inf_value():
    """A list containing float('inf') returns (False, "embedding contains infinite values")."""
    embedding = [0.1, float("inf"), 0.3, 0.4]
    is_valid, reason = validate_embedding(embedding, expected_dim=4)
    assert is_valid is False
    assert reason == "embedding contains infinite values"


def test_validate_neg_inf_value():
    """A list containing float('-inf') returns (False, "embedding contains infinite values")."""
    embedding = [0.1, 0.2, 0.3, float("-inf")]
    is_valid, reason = validate_embedding(embedding, expected_dim=4)
    assert is_valid is False
    assert reason == "embedding contains infinite values"


def test_validate_empty_embedding():
    """An empty list with expected_dim=0 returns (True, "") (edge case)."""
    embedding: list[float] = []
    is_valid, reason = validate_embedding(embedding, expected_dim=0)
    assert is_valid is True
    assert reason == ""


def test_validate_custom_chunk_id():
    """Passing a custom chunk_id does not change the validation result or the reason string."""

    # Valid case with custom chunk_id
    is_valid, reason = validate_embedding([1.0, 2.0], expected_dim=2, chunk_id="doc-42")
    assert is_valid is True
    assert reason == ""

    # Invalid case with custom chunk_id — reason should not contain the chunk_id
    is_valid, reason = validate_embedding(None, expected_dim=2, chunk_id="doc-99")
    assert is_valid is False
    assert reason == "embedding is None"
    assert "doc-99" not in reason
