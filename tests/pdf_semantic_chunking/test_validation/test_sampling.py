"""Unit tests for the validation sampling module.

Tests for :class:`HumanSamplingHelper` covering stratified sampling
and query suggestion generation.
"""

import random

from src.pdf_semantic_chunking.validation.sampling import HumanSamplingHelper

# ======================================================================
# Helpers
# ======================================================================


def _chunk(
    element_type: str = "mixed",
    element_name: str = "",
    interface: str = "",
) -> dict:
    """Build a minimal chunk dict for testing."""
    meta: dict = {"element_type": element_type}
    if element_name:
        meta["element_name"] = element_name
    if interface:
        meta["interface"] = interface
    return {"metadata": meta}


# ======================================================================
# HumanSamplingHelper.sample
# ======================================================================


class TestHumanSamplingHelperSample:
    """Tests for :meth:`HumanSamplingHelper.sample`."""

    def test_sample_respects_sample_size(self):
        """Returns **at most** ``sample_size`` items."""
        chunks = [_chunk(element_type="function") for _ in range(100)]
        result = HumanSamplingHelper().sample(chunks, sample_size=10)
        assert len(result) <= 10

    def test_sample_stratifies_by_element_type(self):
        """Every element_type group present in input is represented in output.

        With sample_size=15 and 3 groups of 20, per_type=5 → 15 items,
        one from each group.
        """
        chunks = (
            [_chunk(element_type="function") for _ in range(20)]
            + [_chunk(element_type="property") for _ in range(20)]
            + [_chunk(element_type="enum") for _ in range(20)]
        )
        random.seed(42)
        result = HumanSamplingHelper().sample(chunks, sample_size=15)
        types_in_result = {c["metadata"]["element_type"] for c in result}
        assert types_in_result == {"function", "property", "enum"}

    def test_sample_empty_list(self):
        """Empty chunks list returns an empty list."""
        result = HumanSamplingHelper().sample([])
        assert result == []

    def test_sample_fewer_chunks_than_sample_size_returns_all(self):
        """When input has fewer items than ``sample_size``, all are returned."""
        chunks = [_chunk() for _ in range(5)]
        result = HumanSamplingHelper().sample(chunks, sample_size=25)
        assert len(result) == 5

    def test_sample_returns_unique_chunks(self):
        """No duplicate chunk references in the sample output."""
        chunks = [_chunk(element_type="function") for _ in range(50)]
        random.seed(123)
        result = HumanSamplingHelper().sample(chunks, sample_size=25)
        ids = [id(c) for c in result]
        assert len(ids) == len(set(ids))

    def test_per_type_distribution_with_uneven_groups(self):
        """Even with uneven group sizes, all types get at least one representative
        when ``sample_size`` is large enough.
        """
        chunks = (
            [_chunk(element_type="function") for _ in range(50)]
            + [_chunk(element_type="property") for _ in range(2)]
            + [_chunk(element_type="enum") for _ in range(1)]
        )
        random.seed(7)
        result = HumanSamplingHelper().sample(chunks, sample_size=10)
        types_in_result = {c["metadata"]["element_type"] for c in result}
        assert types_in_result == {"function", "property", "enum"}

    def test_sample_size_greater_than_total_returns_all(self):
        """If ``sample_size`` > total count, all chunks are returned."""
        chunks = [_chunk(element_type="function") for _ in range(5)]
        random.seed(1)
        result = HumanSamplingHelper().sample(chunks, sample_size=100)
        assert len(result) == 5


# ======================================================================
# HumanSamplingHelper.suggest_queries
# ======================================================================


class TestHumanSamplingHelperSuggestQueries:
    """Tests for :meth:`HumanSamplingHelper.suggest_queries`."""

    def test_generates_query_for_each_element_name(self):
        """Each chunk with an ``element_name`` gets a 'How do I use X?' query."""
        chunks = [
            _chunk(element_name="Method1"),
            _chunk(element_name="Method2"),
        ]
        queries = HumanSamplingHelper().suggest_queries(chunks)

        assert "How do I use Method1?" in queries
        assert "How do I use Method2?" in queries

    def test_with_interface_includes_what_is_query(self):
        """When ``interface`` is present, a 'What is Interface.Name?' query is added."""
        chunks = [
            _chunk(element_name="Method", interface="IFoo"),
        ]
        queries = HumanSamplingHelper().suggest_queries(chunks)

        assert "How do I use Method?" in queries
        assert "What is IFoo.Method?" in queries

    def test_returns_at_most_10_queries(self):
        """Maximum of 10 queries returned regardless of input size."""
        chunks = [_chunk(element_name=f"Method{i}") for i in range(20)]
        queries = HumanSamplingHelper().suggest_queries(chunks)

        assert len(queries) <= 10

    def test_no_element_names_returns_empty(self):
        """When no chunk has ``element_name``, returns an empty list."""
        chunks = [_chunk() for _ in range(5)]
        queries = HumanSamplingHelper().suggest_queries(chunks)

        assert queries == []

    def test_max_queries_respected_with_interface_chunks(self):
        """Even when each chunk generates 2 queries, still at most 10 returned."""
        # 10 chunks × 2 queries each = 20 candidates → sliced to 10
        chunks = [_chunk(element_name=f"M{i}", interface="IFoo") for i in range(10)]
        queries = HumanSamplingHelper().suggest_queries(chunks)

        assert len(queries) == 10

    def test_chunks_without_metadata_key(self):
        """Chunks entirely missing the ``metadata`` key are safely skipped."""
        chunks = [{"no_metadata": True}, {"metadata": {"element_name": "Foo"}}]
        queries = HumanSamplingHelper().suggest_queries(chunks)

        assert queries == ["How do I use Foo?"]
