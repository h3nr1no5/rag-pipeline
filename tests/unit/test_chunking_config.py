"""Unit tests for configurable RecursiveChunkingService features.

Task 9.15 — Configurable min_chunk_length
- Different min_chunk_length values
- Short chunks filtered out
- Default value (20) when None is passed
"""

import pytest

from src.domain.entities import ChunkingStrategy
from src.domain.services.chunking import RecursiveChunkingService, create_chunking_service


@pytest.fixture
def base_strategy():
    return ChunkingStrategy(
        id="test",
        name="Test",
        chunk_size=1000,
        chunk_overlap=50,
        separators=["\n"],
        embedding_model="test-model",
    )


# ---------------------------------------------------------------------------
# Task 9.15 — min_chunk_length
# ---------------------------------------------------------------------------


class TestMinChunkLength:
    def test_default_min_chunk_length(self):
        """Service defaults min_chunk_length to 20 when None is passed."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=1000, chunk_overlap=50,
            separators=["\n"], embedding_model="test",
        )
        service = RecursiveChunkingService(strategy, min_chunk_length=None)
        assert service.min_chunk_length == 20

    def test_explicit_min_chunk_length(self):
        """Service uses the explicitly provided min_chunk_length."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=1000, chunk_overlap=50,
            separators=["\n"], embedding_model="test",
        )
        service = RecursiveChunkingService(strategy, min_chunk_length=50)
        assert service.min_chunk_length == 50

    def test_zero_min_chunk_length_keeps_all(self):
        """min_chunk_length=0 keeps even empty strings."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=1000, chunk_overlap=50,
            separators=["\n"], embedding_model="test",
        )
        service = RecursiveChunkingService(strategy, min_chunk_length=0)
        text = "A"
        chunks = service.chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0]["content"] == "A"

    def test_filter_short_chunks(self):
        """Chunks shorter than min_chunk_length are filtered out."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=1000, chunk_overlap=50,
            separators=["\n"], embedding_model="test",
        )
        service = RecursiveChunkingService(strategy, min_chunk_length=50)
        # Text with 2 paragraphs: one short ("Hi"), one long enough
        text = "Hi\n" + "This is a long paragraph that exceeds the minimum length of fifty characters easily."  # noqa: E501
        chunks = service.chunk_text(text)
        # The short "Hi" chunk should be filtered out
        for chunk in chunks:
            assert len(chunk["content"]) >= 50

    def test_high_min_chunk_length_filters_most(self):
        """A very high min_chunk_length filters most/all chunks."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=1000, chunk_overlap=50,
            separators=["\n"], embedding_model="test",
        )
        service = RecursiveChunkingService(strategy, min_chunk_length=10000)
        text = "Short text."
        chunks = service.chunk_text(text)
        assert len(chunks) == 0

    def test_create_chunking_service_with_config(self):
        """create_chunking_service reads min_chunk_length from strategy config."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=1000, chunk_overlap=50,
            separators=["\n"], embedding_model="test",
            config={"min_chunk_length": 100},
        )
        service = create_chunking_service(strategy)
        assert service.min_chunk_length == 100

    def test_create_chunking_service_default_when_no_config(self):
        """create_chunking_service defaults to 20 when config is None."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=1000, chunk_overlap=50,
            separators=["\n"], embedding_model="test",
            config=None,
        )
        service = create_chunking_service(strategy)
        assert service.min_chunk_length == 20

    def test_create_chunking_service_default_when_key_missing(self):
        """create_chunking_service defaults to 20 when min_chunk_length not in config."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=1000, chunk_overlap=50,
            separators=["\n"], embedding_model="test",
            config={"other_key": "value"},
        )
        service = create_chunking_service(strategy)
        assert service.min_chunk_length == 20

    def test_min_chunk_length_affects_token_chunking(self):
        """min_chunk_length also affects chunk_text_by_tokens output."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=100, chunk_overlap=0,
            separators=["\n"], embedding_model="test",
        )
        service = RecursiveChunkingService(strategy, min_chunk_length=100)
        text = "a b c d"
        chunks = service.chunk_text_by_tokens(text)
        # Very short text → should be filtered
        assert len(chunks) == 0

    def test_min_chunk_length_preserves_long_enough(self):
        """Chunks that meet min_chunk_length are kept."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=1000, chunk_overlap=50,
            separators=["\n"], embedding_model="test",
        )
        service = RecursiveChunkingService(strategy, min_chunk_length=10)
        text = "This is a reasonably long text that should definitely be kept as a chunk."
        chunks = service.chunk_text(text)
        assert len(chunks) == 1
        assert len(chunks[0]["content"]) >= 10

    def test_create_chunking_service_no_args(self):
        """create_chunking_service returns a service with proper defaults."""
        strategy = ChunkingStrategy(
            id="test", name="Test", chunk_size=500, chunk_overlap=25,
            separators=["\n\n"], embedding_model="test",
        )
        service = create_chunking_service(strategy)
        assert isinstance(service, RecursiveChunkingService)
        assert service.strategy == strategy
