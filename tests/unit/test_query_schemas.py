"""Unit tests for async query Pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.schemas.query import (
    BackendResultSchema,
    QueryStartRequest,
    QueryStartResponse,
    SourceChunk,
    TaskStatusResponse,
)


class TestQueryStartRequest:
    """Tests for QueryStartRequest schema (async query start)."""

    def test_valid_request_with_required_fields(self):
        """A request with only the required question field should work."""
        data = {"question": "What is this document about?"}
        req = QueryStartRequest(**data)
        assert req.question == "What is this document about?"
        assert req.document_ids == []
        assert req.backends == ["cosine", "langchain", "llamaindex"]

    def test_valid_request_with_all_fields(self):
        """A fully populated request should parse correctly."""
        data = {
            "question": "Test question?",
            "document_ids": ["doc-1", "doc-2"],
            "temperature": 0.3,
            "max_tokens": 1024,
            "top_k": 10,
            "prompt_sources": 5,
            "include_citations": False,
            "response_length": "concise",
            "clean_response": False,
            "link_decay_factor": 0.5,
            "link_expansion_factor": 3,
            "enable_rag": True,
            "enable_docs": False,
            "backends": ["cosine"],
        }
        req = QueryStartRequest(**data)
        assert req.question == "Test question?"
        assert req.document_ids == ["doc-1", "doc-2"]
        assert req.temperature == 0.3
        assert req.max_tokens == 1024

    def test_question_min_length_validation(self):
        """Question must be at least 1 character."""
        with pytest.raises(ValidationError) as exc:
            QueryStartRequest(question="")
        errors = exc.value.errors()
        assert any("question" in err["loc"] for err in errors)

    def test_question_max_length_validation(self):
        """Question must not exceed 2000 characters."""
        with pytest.raises(ValidationError) as exc:
            QueryStartRequest(question="x" * 2001)
        errors = exc.value.errors()
        assert any("question" in err["loc"] for err in errors)

    def test_question_at_exactly_2000_chars(self):
        """A question of exactly 2000 characters should be valid."""
        req = QueryStartRequest(question="x" * 2000)
        assert len(req.question) == 2000

    def test_max_tokens_range_low(self):
        """max_tokens below 50 should raise."""
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", max_tokens=10)

    def test_max_tokens_range_high(self):
        """max_tokens above 4096 should raise."""
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", max_tokens=5000)

    def test_max_tokens_at_boundaries(self):
        """max_tokens at 50 and 4096 should be valid."""
        req_low = QueryStartRequest(question="test", max_tokens=50)
        assert req_low.max_tokens == 50

        req_high = QueryStartRequest(question="test", max_tokens=4096)
        assert req_high.max_tokens == 4096

    def test_temperature_range_low(self):
        """temperature below 0.0 should raise."""
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", temperature=-0.1)

    def test_temperature_range_high(self):
        """temperature above 1.0 should raise."""
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", temperature=1.5)

    def test_temperature_at_boundaries(self):
        """temperature at 0.0 and 1.0 should be valid."""
        req_low = QueryStartRequest(question="test", temperature=0.0)
        assert req_low.temperature == 0.0

        req_high = QueryStartRequest(question="test", temperature=1.0)
        assert req_high.temperature == 1.0

    def test_backends_valid_values(self):
        """All valid backends should be accepted."""
        valid_sets = [
            ["cosine"],
            ["langchain"],
            ["llamaindex"],
            ["cosine", "langchain"],
            ["cosine", "langchain", "llamaindex"],
        ]
        for backends in valid_sets:
            req = QueryStartRequest(question="test", backends=backends)
            assert req.backends == backends

    def test_backends_invalid_value_raises(self):
        """An invalid backend value should raise a ValueError."""
        with pytest.raises(ValidationError) as exc:
            QueryStartRequest(question="test", backends=["invalid_backend"])
        errors = exc.value.errors()
        assert any("backends" in err["loc"] for err in errors)

    def test_backends_multiple_invalid_values(self):
        """Multiple invalid backend values should all be caught."""
        with pytest.raises(ValidationError):
            QueryStartRequest(
                question="test",
                backends=["cosine", "bad_backend", "another_bad"],
            )

    def test_backends_empty_list(self):
        """An empty backends list should be valid (though no backends will run)."""
        req = QueryStartRequest(question="test", backends=[])
        assert req.backends == []

    def test_default_values(self):
        """Default values should be set correctly."""
        req = QueryStartRequest(question="test")
        assert req.document_ids == []
        assert req.temperature == 0.5
        assert req.max_tokens == 600
        assert req.top_k == 5
        assert req.prompt_sources == 3
        assert req.include_citations is True
        assert req.response_length == "normal"
        assert req.clean_response is True
        assert req.link_decay_factor == 0.85
        assert req.link_expansion_factor == 2
        assert req.enable_rag is True
        assert req.enable_docs is True
        assert req.backends == ["cosine", "langchain", "llamaindex"]

    def test_response_length_pattern(self):
        """response_length must match the regex pattern."""
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", response_length="extra_long")

        for val in ("concise", "normal", "detailed"):
            req = QueryStartRequest(question="test", response_length=val)
            assert req.response_length == val

    def test_top_k_range(self):
        """top_k must be between 1 and 20."""
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", top_k=0)
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", top_k=21)

        req = QueryStartRequest(question="test", top_k=1)
        assert req.top_k == 1

        req = QueryStartRequest(question="test", top_k=20)
        assert req.top_k == 20

    def test_prompt_sources_range(self):
        """prompt_sources must be between 1 and 10."""
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", prompt_sources=0)
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", prompt_sources=11)

    def test_link_decay_factor_range(self):
        """link_decay_factor must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", link_decay_factor=-0.1)
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", link_decay_factor=1.1)

    def test_link_expansion_factor_range(self):
        """link_expansion_factor must be between 1 and 10."""
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", link_expansion_factor=0)
        with pytest.raises(ValidationError):
            QueryStartRequest(question="test", link_expansion_factor=11)


class TestQueryStartResponse:
    """Tests for QueryStartResponse schema."""

    def test_create_with_task_id_and_status(self):
        """QueryStartResponse should store task_id and status."""
        resp = QueryStartResponse(task_id="abc123", status="pending")
        assert resp.task_id == "abc123"
        assert resp.status == "pending"

    def test_create_with_running_status(self):
        """The status should accept 'running'."""
        resp = QueryStartResponse(task_id="xyz", status="running")
        assert resp.status == "running"


class TestTaskStatusResponse:
    """Tests for TaskStatusResponse schema."""

    def test_create_with_all_fields(self):
        """TaskStatusResponse should accept all fields."""
        resp = TaskStatusResponse(
            task_id="task-1",
            status="completed",
            results=[],
            progress={"cosine": "completed"},
            error=None,
            created_at=1000.0,
            completed_at=1100.0,
        )
        assert resp.task_id == "task-1"
        assert resp.status == "completed"
        assert resp.results == []
        assert resp.progress == {"cosine": "completed"}
        assert resp.error is None
        assert resp.created_at == 1000.0
        assert resp.completed_at == 1100.0

    def test_create_with_minimal_fields(self):
        """TaskStatusResponse should work with only required fields."""
        resp = TaskStatusResponse(
            task_id="task-1",
            status="pending",
            created_at=1000.0,
        )
        assert resp.results == []
        assert resp.progress == {}
        assert resp.error is None
        assert resp.completed_at is None

    def test_create_with_error(self):
        """TaskStatusResponse should accept an error message."""
        resp = TaskStatusResponse(
            task_id="task-1",
            status="failed",
            error="All backends failed",
            created_at=1000.0,
        )
        assert resp.error == "All backends failed"

    def test_create_with_results(self):
        """TaskStatusResponse should accept a list of backend results."""
        result1 = BackendResultSchema(
            backend="cosine",
            answer="Answer 1",
            sources=[],
        )
        result2 = BackendResultSchema(
            backend="langchain",
            answer="Answer 2",
            sources=[SourceChunk(chunk_id="c1", content="content", score=0.95)],
        )
        resp = TaskStatusResponse(
            task_id="task-1",
            status="completed",
            results=[result1, result2],
            created_at=1000.0,
            completed_at=1100.0,
        )
        assert len(resp.results) == 2
        assert resp.results[0].backend == "cosine"
        assert resp.results[1].backend == "langchain"
        assert len(resp.results[1].sources) == 1


class TestBackendResultSchema:
    """Tests for BackendResultSchema."""

    def test_create_with_all_fields(self):
        """BackendResultSchema should accept all fields."""
        result = BackendResultSchema(
            backend="cosine",
            answer="The answer is 42.",
            sources=[
                SourceChunk(chunk_id="c1", content="relevant content", score=0.95),
            ],
            error=None,
            cached=False,
        )
        assert result.backend == "cosine"
        assert result.answer == "The answer is 42."
        assert len(result.sources) == 1
        assert result.sources[0].chunk_id == "c1"
        assert result.error is None
        assert result.cached is False

    def test_create_with_error(self):
        """BackendResultSchema should accept an error string."""
        result = BackendResultSchema(
            backend="llamaindex",
            answer="",
            sources=[],
            error="backend_error",
        )
        assert result.error == "backend_error"

    def test_create_with_cached_true(self):
        """BackendResultSchema should accept cached=True."""
        result = BackendResultSchema(
            backend="cosine",
            answer="cached answer",
            sources=[],
            cached=True,
        )
        assert result.cached is True

    def test_create_empty_sources_default(self):
        """BackendResultSchema should default to empty sources list."""
        result = BackendResultSchema(
            backend="cosine",
            answer="answer",
        )
        assert result.sources == []
        assert result.error is None
        assert result.cached is False

    def test_error_optional_defaults_to_none(self):
        """BackendResultSchema.error should default to None."""
        result = BackendResultSchema(backend="cosine", answer="answer")
        assert result.error is None
