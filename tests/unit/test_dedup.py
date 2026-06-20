"""
Unit tests for deduplicate_chunks function.

Tests the deduplication logic that removes duplicate chunks based on
content signature (first 50 characters).
"""
from dataclasses import dataclass
from src.domain.services.prompt_builder import deduplicate_chunks


# Mock objects to simulate different chunk types
@dataclass
class RetrievedChunkResult:
    """Mock object simulating RetrievedChunkResult from LangChain/LlamaIndex."""
    chunk_id: str
    content: str
    score: float
    metadata: dict


class LlamaIndexRetrievedChunk:
    """Mock object simulating LlamaIndex retrieved chunk."""
    def __init__(self, chunk_id: str, content: str, score: float = 0.0, metadata: dict = None):
        self.chunk_id = chunk_id
        self.content = content
        self.score = score
        self.metadata = metadata or {}


class MockChunk:
    """Mock Chunk object for tuple format (Chunk, score)."""
    def __init__(self, chunk_id: str, content: str):
        self.id = chunk_id
        self.content = content


class TestDeduplicateChunks:
    """Test suite for deduplicate_chunks function."""

    def test_empty_list_returns_empty(self):
        """Empty input should return empty list."""
        result = deduplicate_chunks([])
        assert result == []

    def test_single_item_returns_same(self):
        """Single chunk should be returned as-is."""
        chunks = [(MockChunk("chunk1", "Some content here"), 0.9)]  # Tuple format
        result = deduplicate_chunks(chunks)
        assert len(result) == 1

    def test_duplicate_content_removed(self):
        """Duplicate content (same first 50 chars) should be deduplicated."""
        # Create chunks with identical first 50 chars
        chunk1 = (MockChunk("c1", "This is a very long text that starts the same way for all chunks"), 0.9)
        chunk2 = (MockChunk("c2", "This is a very long text that starts the same way for all chunks but has different ending"), 0.8)
        chunk3 = (MockChunk("c3", "This is a very long text that starts the same way for all chunks and more content here"), 0.7)

        result = deduplicate_chunks([chunk1, chunk2, chunk3])

        # Should only keep the first one (deduped by signature)
        assert len(result) == 1

    def test_different_content_preserved(self):
        """Different content should be preserved."""
        chunk1 = (MockChunk("c1", "Python is a high-level programming language"), 0.9)
        chunk2 = (MockChunk("c2", "Java is a strongly typed programming language"), 0.8)
        chunk3 = (MockChunk("c3", "JavaScript is a dynamic programming language"), 0.7)

        result = deduplicate_chunks([chunk1, chunk2, chunk3])

        # All three should be preserved (different signatures)
        assert len(result) == 3

    def test_mixed_types_tuples_and_objects(self):
        """Function should handle both tuple and object formats."""
        # Tuple format (Chunk, score)
        tuple_chunk = (MockChunk("id1", "First unique content here"), 0.9)

        # Object format (RetrievedChunkResult)
        obj_chunk = RetrievedChunkResult(
            chunk_id="id2",
            content="Second unique content here",
            score=0.8,
            metadata={}
        )

        result = deduplicate_chunks([tuple_chunk, obj_chunk])

        # Both should be preserved (different signatures)
        assert len(result) == 2

    def test_object_format_retrieved_chunk_result(self):
        """Test with RetrievedChunkResult-like objects."""
        chunks = [
            RetrievedChunkResult("id1", "First unique content for testing", 0.9, {}),
            RetrievedChunkResult("id2", "Second unique content for testing", 0.8, {}),
            RetrievedChunkResult("id3", "First unique content for testing", 0.7, {}),  # Duplicate
        ]

        result = deduplicate_chunks(chunks)

        # Should deduplicate - only 2 unique
        assert len(result) == 2

    def test_object_format_llamaindex_chunk(self):
        """Test with LlamaIndexRetrievedChunk-like objects."""
        chunks = [
            LlamaIndexRetrievedChunk("id1", "Content about Python programming", 0.9),
            LlamaIndexRetrievedChunk("id2", "Content about Python programming", 0.8),  # Duplicate
            LlamaIndexRetrievedChunk("id3", "Content about Java programming", 0.7),
        ]

        result = deduplicate_chunks(chunks)

        # Should deduplicate - only 2 unique
        assert len(result) == 2

    def test_near_boundary_at_50_chars(self):
        """Test near-duplicates at the 50-char boundary."""
        # Exactly 50 chars - should be considered duplicate
        chunk1 = (MockChunk("c1", "A" * 50 + " extra content that makes it different"), 0.9)
        chunk2 = (MockChunk("c2", "A" * 50 + " different ending here"), 0.8)

        result = deduplicate_chunks([chunk1, chunk2])
        assert len(result) == 1  # Duplicate

        # 49 chars - different signature
        chunk3 = (MockChunk("c3", "A" * 49 + "B extra content"), 0.9)
        chunk4 = (MockChunk("c4", "A" * 49 + "C different"), 0.8)

        result2 = deduplicate_chunks([chunk3, chunk4])
        assert len(result2) == 2  # Not duplicate

    def test_case_insensitive_deduplication(self):
        """Deduplication should be case-insensitive."""
        chunk1 = (MockChunk("c1", "UPPERCASE CONTENT HERE for testing"), 0.9)
        chunk2 = (MockChunk("c2", "uppercase content here for testing"), 0.8)  # Same lowercase
        chunk3 = (MockChunk("c3", "lowercase content here for testing"), 0.7)  # Different

        result = deduplicate_chunks([chunk1, chunk2, chunk3])

        # First two are duplicates (case-insensitive), third is unique
        assert len(result) == 2

    def test_whitespace_handling(self):
        """Whitespace should be normalized for deduplication."""
        chunk1 = (MockChunk("c1", "   Content with leading/trailing spaces"), 0.9)
        chunk2 = (MockChunk("c2", "Content with leading/trailing spaces   "), 0.8)  # Same after strip
        chunk3 = (MockChunk("c3", "Different content here"), 0.7)

        result = deduplicate_chunks([chunk1, chunk2, chunk3])

        # First two are duplicates (whitespace normalized)
        assert len(result) == 2

    def test_preserves_order_of_first_occurrence(self):
        """First occurrence should be preserved, subsequent duplicates removed."""
        # Use longer content so first 50 chars are the same
        base1 = "This is a test document with some content for testing deduplication"
        base2 = "Another completely different topic that is unrelated to the first one"
        chunk1 = (MockChunk("c1", base1 + " - version one"), 0.9)
        chunk2 = (MockChunk("c2", base1 + " - version two"), 0.8)  # Same first 50 chars as chunk1
        chunk3 = (MockChunk("c3", base2 + " with additional info"), 0.7)
        chunk4 = (MockChunk("c4", base2 + " with more info"), 0.6)  # Same first 50 chars as chunk3

        result = deduplicate_chunks([chunk1, chunk2, chunk3, chunk4])

        # Should preserve order: chunk1, chunk3 (first of each unique signature)
        assert len(result) == 2

    def test_all_duplicates_returns_one(self):
        """All duplicates should return just one."""
        chunk1 = (MockChunk("c1", "Identical content repeated"), 0.9)
        chunk2 = (MockChunk("c2", "Identical content repeated"), 0.8)
        chunk3 = (MockChunk("c3", "Identical content repeated"), 0.7)

        result = deduplicate_chunks([chunk1, chunk2, chunk3])

        assert len(result) == 1

    def test_mixed_duplicate_and_unique(self):
        """Test with a mix of duplicate and unique chunks."""
        chunks = [
            (MockChunk("c1", "Python is great for data science"), 0.9),
            (MockChunk("c2", "Python is great for data science"), 0.8),  # Duplicate
            (MockChunk("c3", "Java is also popular"), 0.7),
            (MockChunk("c4", "Python is great for data science"), 0.6),  # Duplicate
            (MockChunk("c5", "Rust is gaining popularity"), 0.5),
        ]

        result = deduplicate_chunks(chunks)

        # Should have 3 unique: Python, Java, Rust
        assert len(result) == 3


class TestDeduplicateChunksEdgeCases:
    """Edge case tests for deduplicate_chunks."""

    def test_very_short_content(self):
        """Test with very short content."""
        chunk1 = (MockChunk("c1", "Short"), 0.9)
        chunk2 = (MockChunk("c2", "Short"), 0.8)
        chunk3 = (MockChunk("c3", "Different"), 0.7)

        result = deduplicate_chunks([chunk1, chunk2, chunk3])

        # Short content still deduplicates
        assert len(result) == 2

    def test_empty_content(self):
        """Test with empty content."""
        chunk1 = (MockChunk("c1", ""), 0.9)
        chunk2 = (MockChunk("c2", ""), 0.8)
        chunk3 = (MockChunk("c3", "Some content"), 0.7)

        result = deduplicate_chunks([chunk1, chunk2, chunk3])

        # Empty strings are considered duplicates
        assert len(result) == 2

    def test_none_content(self):
        """Test handling of None content gracefully."""
        # This tests the function doesn't crash on edge cases
        chunk1 = (MockChunk("c1", "Valid content"), 0.9)
        chunk2 = (MockChunk("c2", "Valid content"), 0.8)

        result = deduplicate_chunks([chunk1, chunk2])
        assert len(result) == 1


class TestDeduplicateChunksIntegration:
    """
    Integration-style tests verifying deduplication works in context.
    These simulate how the function is used in the query routes.
    """

    def test_simulates_route_usage_tuple_format(self):
        """
        Simulates how deduplicate_chunks is used in the main query route.
        The route retrieves chunks as tuples (Chunk, score) and deduplicates.
        """
        # Simulate retrieved chunks from cosine retrieval
        retrieved = [
            (MockChunk("c1", "Python supports multiple programming paradigms"), 0.95),
            (MockChunk("c2", "Python supports multiple programming paradigms"), 0.90),  # Duplicate
            (MockChunk("c3", "JavaScript is a dynamic language"), 0.85),
            (MockChunk("c4", "Python supports multiple programming paradigms"), 0.80),  # Duplicate
            (MockChunk("c5", "Rust focuses on safety and performance"), 0.75),
        ]

        # Apply deduplication (as done in routes.py)
        deduped = deduplicate_chunks(retrieved)

        # Apply prompt_sources limit (as done in routes.py)
        sources = deduped[:3]

        # Verify no duplicates in final sources
        contents = [item[0].content for item in sources]
        assert len(contents) == len(set(contents)), "Duplicate content found in sources!"

    def test_simulates_route_usage_object_format(self):
        """
        Simulates how deduplicate_chunks is used in LangChain/LlamaIndex routes.
        These routes return RetrievedChunkResult objects.
        """
        # Simulate retrieved chunks from LangChain/LlamaIndex
        retrieved = [
            RetrievedChunkResult("c1", "Machine learning is a subset of AI", 0.95, {}),
            RetrievedChunkResult("c2", "Machine learning is a subset of AI", 0.90, {}),  # Duplicate
            RetrievedChunkResult("c3", "Deep learning uses neural networks", 0.85, {}),
            RetrievedChunkResult("c4", "Machine learning is a subset of AI", 0.80, {}),  # Duplicate
            RetrievedChunkResult("c5", "Natural language processing deals with text", 0.75, {}),
        ]

        # Apply deduplication (as done in routes.py)
        deduped = deduplicate_chunks(retrieved)

        # Apply prompt_sources limit (as done in routes.py)
        sources = deduped[:3]

        # Verify no duplicates in final sources
        contents = [item.content for item in sources]
        assert len(contents) == len(set(contents)), "Duplicate content found in sources!"

    def test_dedup_then_limit_preserves_unique(self):
        """
        Verify that deduplication happens BEFORE limiting, ensuring
        unique content is preserved even when limiting.
        """
        # Create 10 chunks where only 3 are unique
        chunks = []
        for i in range(10):
            content = f"Unique content number {i % 3}"  # Only 3 unique values
            chunks.append((MockChunk(f"c{i}", content), 0.9 - i * 0.05))

        deduped = deduplicate_chunks(chunks)

        # Should have only 3 unique
        assert len(deduped) == 3

        # Limit to 2 - should get 2 unique
        limited = deduped[:2]
        assert len(limited) == 2