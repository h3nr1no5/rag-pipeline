import pytest
from src.domain.services.chunking import RecursiveChunkingService, create_chunking_service
from src.domain.entities import ChunkingStrategy


@pytest.fixture
def default_strategy():
    return ChunkingStrategy(
        id="recursive",
        name="Recursive",
        chunk_size=100,
        chunk_overlap=20,
        separators=["\n\n", "\n", ". "],
        embedding_model="test-model",
    )


def test_chunk_text_basic(default_strategy):
    service = RecursiveChunkingService(default_strategy)
    
    text = "This is a test paragraph.\n\nThis is another paragraph."
    chunks = service.chunk_text(text)
    
    assert len(chunks) > 0
    assert all("content" in chunk for chunk in chunks)
    assert all("chunk_index" in chunk for chunk in chunks)


def test_chunk_text_preserves_content(default_strategy):
    service = RecursiveChunkingService(default_strategy)
    
    text = "Hello world. This is a test."
    chunks = service.chunk_text(text)
    
    combined = " ".join(chunk["content"] for chunk in chunks)
    assert "Hello" in combined or "world" in combined


def test_chunk_index_sequential(default_strategy):
    service = RecursiveChunkingService(default_strategy)
    
    text = "\n\n".join([f"Paragraph {i}" * 50 for i in range(10)])
    chunks = service.chunk_text(text)
    
    indices = [chunk["chunk_index"] for chunk in chunks]
    assert indices == list(range(len(chunks)))


def test_metadata_included(default_strategy):
    service = RecursiveChunkingService(default_strategy)
    
    text = "This is a test paragraph for metadata."
    chunks = service.chunk_text(text)
    
    assert len(chunks) > 0
    assert "metadata" in chunks[0]
    assert "chunking_strategy_id" in chunks[0]["metadata"]


def test_create_chunking_service():
    strategy = ChunkingStrategy(
        id="test",
        name="Test",
        chunk_size=50,
        chunk_overlap=10,
        separators=["\n"],
        embedding_model="test",
    )
    
    service = create_chunking_service(strategy)
    assert isinstance(service, RecursiveChunkingService)
    assert service.strategy == strategy


def test_empty_text(default_strategy):
    service = RecursiveChunkingService(default_strategy)
    
    chunks = service.chunk_text("")
    assert len(chunks) == 0


def test_small_chunks_filtered(default_strategy):
    service = RecursiveChunkingService(default_strategy)
    
    text = "Hi"
    chunks = service.chunk_text(text)
    
    for chunk in chunks:
        assert len(chunk["content"].strip()) >= 20
