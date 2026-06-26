"""Integration tests for fallback and graceful degradation of the pipeline.

Tests cover:
- Non-COM PDF graceful degradation
- Metadata enrichment fallback with sparse metadata
- ChunkAssembler forced merging with large min_tokens
- Empty document handling
- HumanSamplingHelper edge cases
"""

import os
import tempfile

import pytest

from src.pdf_semantic_chunking.api import chunk_pdf
from src.pdf_semantic_chunking.chunking.assembler import ChunkAssembler
from src.pdf_semantic_chunking.chunking.metadata import MetadataEnricher
from src.pdf_semantic_chunking.extraction.model import DocumentElement, DocumentHierarchy
from src.pdf_semantic_chunking.pipeline.context import ChunkData
from src.pdf_semantic_chunking.validation.sampling import HumanSamplingHelper

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "fixtures"
)




# ======================================================================
# test_non_com_pdf_graceful_degradation
# ======================================================================


class TestNonComPdfGracefulDegradation:
    """Run the full pipeline on a non-COM PDF (unstructured.pdf)."""

    @pytest.mark.asyncio
    async def test_pipeline_completes_and_has_chunks(self):
        """Pipeline completes successfully and produces chunks with unstructured prose."""
        file_path = os.path.join(FIXTURE_DIR, "unstructured.pdf")
        result = await chunk_pdf(file_path)
        assert "chunks" in result
        assert "stats" in result
        assert len(result["chunks"]) > 0, "Expected at least one chunk from unstructured.pdf"

    @pytest.mark.asyncio
    async def test_element_type_is_not_com_type(self):
        """element_type in chunk metadata is NOT one of COM types."""
        file_path = os.path.join(FIXTURE_DIR, "unstructured.pdf")
        result = await chunk_pdf(file_path)
        com_types = {"function", "property", "enum", "record", "error_code"}
        for chunk in result["chunks"]:
            etype = chunk.get("metadata", {}).get("element_type", "")
            assert etype not in com_types, (
                f"Chunk {chunk.get('chunk_index')} has COM element_type '{etype}'"
            )

    @pytest.mark.asyncio
    async def test_confidence_present_with_default(self):
        """confidence should be present in metadata (default 1.0 for non-COM content)."""
        file_path = os.path.join(FIXTURE_DIR, "unstructured.pdf")
        result = await chunk_pdf(file_path)
        for chunk in result["chunks"]:
            confidence = chunk.get("metadata", {}).get("confidence")
            assert confidence is not None, (
                f"Chunk {chunk.get('chunk_index')} missing 'confidence'"
            )
            assert confidence == 1.0

    @pytest.mark.asyncio
    async def test_chunks_contain_content(self):
        """Each chunk has non-empty content from the unstructured PDF."""
        file_path = os.path.join(FIXTURE_DIR, "unstructured.pdf")
        result = await chunk_pdf(file_path)
        for chunk in result["chunks"]:
            assert chunk.get("content"), (
                f"Chunk {chunk.get('chunk_index')} has empty content"
            )


# ======================================================================
# test_metadata_fallback
# ======================================================================


class TestMetadataFallback:
    """MetadataEnricher with sparse metadata still enriches correctly."""

    def setup_method(self):
        self.enricher = MetadataEnricher()

    def test_minimal_metadata_still_enriches(self):
        """A chunk with nearly empty metadata still gets chunk_id, source_document, created_at."""
        chunk = ChunkData(content="some content", metadata={}, chunk_index=0)
        result = self.enricher.enrich([chunk], "/path/to/doc.pdf")
        assert len(result) == 1
        meta = result[0].metadata
        assert "chunk_id" in meta
        assert "source_document" in meta
        assert "created_at" in meta
        assert meta["source_document"] == "doc.pdf"
        assert meta["chunk_id"] != ""

    def test_no_element_name_no_keywords(self):
        """When element_name is absent/missing, keywords are NOT added."""
        chunk = ChunkData(content="some content", metadata={"element_type": "mixed"}, chunk_index=0)
        result = self.enricher.enrich([chunk], "doc.pdf")
        assert "keywords" not in result[0].metadata

    def test_empty_element_name_no_keywords(self):
        """When element_name is an empty string, keywords are NOT added."""
        chunk = ChunkData(
            content="some content",
            metadata={"element_name": ""},
            chunk_index=0,
        )
        result = self.enricher.enrich([chunk], "doc.pdf")
        assert "keywords" not in result[0].metadata

    def test_element_name_present_keywords_added(self):
        """When element_name is present and non-empty, keywords are extracted."""
        chunk = ChunkData(
            content="some content",
            metadata={"element_name": "GetFoo"},
            chunk_index=0,
        )
        result = self.enricher.enrich([chunk], "doc.pdf")
        keywords = result[0].metadata.get("keywords")
        assert keywords is not None
        assert "get" in keywords
        assert "foo" in keywords

    def test_multiple_chunks_with_sparse_metadata(self):
        """All chunks get enriched even when some have sparse metadata."""
        chunks = [
            ChunkData(content="A", metadata={"element_name": "Foo"}, chunk_index=0),
            ChunkData(content="B", metadata={}, chunk_index=1),
            ChunkData(content="C", metadata={"element_type": "mixed"}, chunk_index=2),
        ]
        result = self.enricher.enrich(chunks, "source.pdf")
        assert len(result) == 3
        for r in result:
            assert "chunk_id" in r.metadata
            assert "source_document" in r.metadata
            assert "created_at" in r.metadata

    def test_input_content_preserved_after_enrichment(self):
        """Original chunk content is preserved after metadata enrichment."""
        chunk = ChunkData(content="original text", metadata={}, chunk_index=0)
        result = self.enricher.enrich([chunk], "doc.pdf")
        assert result[0].content == "original text"


# ======================================================================
# test_split_fallback
# ======================================================================


class TestSplitFallback:
    """ChunkAssembler with very large chunk size forces merging."""

    def test_very_large_min_tokens_merges_most_chunks(self):
        """With very large max_tokens (min_chunk_size=99999), most content merges."""
        assembler = ChunkAssembler(max_tokens=399996, chunk_overlap=0)
        els = [
            DocumentElement(type="PARAGRAPH", content="Hello world."),
            DocumentElement(type="PARAGRAPH", content="This is another paragraph."),
            DocumentElement(type="HEADING", content="# Section One"),
            DocumentElement(type="PARAGRAPH", content="More content here."),
            DocumentElement(type="PARAGRAPH", content="Even more text."),
        ]
        root = DocumentElement(type="PAGE", content="")
        root.children = els
        hierarchy = DocumentHierarchy(root=root)
        chunks = assembler.assemble(hierarchy, [])
        # With such high min_chunk_size (=99999), all content should merge
        assert len(chunks) <= 2
        assert len(chunks) >= 1

    def test_large_min_tokens_single_element_stays_single(self):
        """A single large paragraph stays as one chunk even with huge max_tokens."""
        assembler = ChunkAssembler(max_tokens=399996, chunk_overlap=0)
        els = [
            DocumentElement(type="PARAGRAPH", content=" ".join(["word"] * 500)),
        ]
        root = DocumentElement(type="PAGE", content="")
        root.children = els
        hierarchy = DocumentHierarchy(root=root)
        chunks = assembler.assemble(hierarchy, [])
        assert len(chunks) == 1

    def test_min_tokens_zero_allows_many_chunks(self):
        """With boundaries and content exceeding min_chunk_size, content splits."""
        assembler = ChunkAssembler(max_tokens=200, chunk_overlap=0)
        els = [
            DocumentElement(type="PARAGRAPH", content="A " * 100),
            DocumentElement(type="HEADING", content="# Split Here"),
            DocumentElement(type="PARAGRAPH", content="B " * 100),
        ]
        root = DocumentElement(type="PAGE", content="")
        root.children = els
        hierarchy = DocumentHierarchy(root=root)

        # flat = [PAGE(0), PARAGRAPH(1), HEADING(2), PARAGRAPH(3)]
        # _strip_root check: len(flat) == 4, not 1, so returns flat as-is.
        # Boundary at index 2 = the HEADING element, splits before it.
        # → segment 0: [PAGE(0), PARAGRAPH(1)] → PAGE empty → only PARAGRAPH content (~100 tokens)
        # → segment 1: [HEADING(2), PARAGRAPH(3)] → ~101 tokens
        # Both > min_chunk_size (50), won't merge → 2 chunks.
        chunks = assembler.assemble(hierarchy, [2])
        assert len(chunks) >= 2


# ======================================================================
# test_empty_document
# ======================================================================


class TestEmptyDocument:
    """Run the pipeline on a minimal (blank) PDF."""

    @pytest.fixture
    def blank_pdf_path(self):
        """Create a temporary blank PDF with a single empty page."""
        import fitz

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        doc = fitz.open()
        doc.new_page(width=612, height=792)
        doc.save(tmp_path)
        doc.close()
        yield tmp_path
        os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_blank_pdf_completes_without_error(self, blank_pdf_path):
        """Pipeline completes without raising on a blank PDF."""
        result = await chunk_pdf(blank_pdf_path)
        # Should not throw; result may have empty chunks or one chunk
        assert isinstance(result, dict)
        assert "chunks" in result
        assert "stats" in result

    @pytest.mark.asyncio
    async def test_blank_pdf_may_produce_zero_or_one_chunks(self, blank_pdf_path):
        """A blank PDF produces either zero or one chunk."""
        result = await chunk_pdf(blank_pdf_path)
        assert len(result["chunks"]) <= 1

    @pytest.mark.asyncio
    async def test_blank_pdf_stats_structure(self, blank_pdf_path):
        """Stats dict has expected keys even for empty document."""
        result = await chunk_pdf(blank_pdf_path)
        stats = result["stats"]
        assert "chunk_count" in stats
        assert "total_tokens" in stats
        assert "elapsed_seconds" in stats
        assert stats["chunk_count"] <= 1


# ======================================================================
# test_sampling_fallback_edge_case
# ======================================================================


class TestSamplingFallbackEdgeCase:
    """HumanSamplingHelper edge cases."""

    def test_sampling_empty_list_returns_empty_list(self):
        """HumanSamplingHelper.sample([]) returns an empty list."""
        helper = HumanSamplingHelper()
        result = helper.sample([])
        assert result == []

    def test_sampling_single_chunk_returns_that_chunk(self):
        """With a single chunk, the sample returns that chunk."""
        helper = HumanSamplingHelper()
        chunks = [{"metadata": {"element_type": "function"}}]
        result = helper.sample(chunks, sample_size=25)
        assert len(result) == 1
        assert result[0] is chunks[0]

    def test_sampling_single_chunk_small_sample_size(self):
        """With a single chunk and sample_size smaller than 1, still returns chunk."""
        helper = HumanSamplingHelper()
        chunks = [{"metadata": {"element_type": "function"}}]
        result = helper.sample(chunks, sample_size=1)
        assert len(result) == 1

    def test_sampling_two_chunks_same_type(self):
        """Two chunks of the same type: per_type = max(1, sample_size // 1) = 25, capped to 25."""
        helper = HumanSamplingHelper()
        chunks = [
            {"metadata": {"element_type": "function"}},
            {"metadata": {"element_type": "function"}},
        ]
        result = helper.sample(chunks, sample_size=25)
        assert len(result) == 2


# ======================================================================
# xfail variant for the known bug (strict)
# ======================================================================


class TestSamplingFallbackXfail:
    """Empty input handling — bug is now fixed."""

    def test_empty_list_returns_empty_list(self):
        """Empty list should return empty list."""
        helper = HumanSamplingHelper()
        result = helper.sample([])
        assert result == []
