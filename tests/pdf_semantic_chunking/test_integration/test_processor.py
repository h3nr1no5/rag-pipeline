"""Integration tests for the processor code path that routes to the semantic chunker.

Tests cover:
- chunk_pdf() API function directly on fixture PDFs
- build_augmented_text integration with pipeline output
- Error handling for non-existent files
- Augmentation of non-COM chunks
- SemanticChunkingError sanitization (to_dict)
"""

import os
import sys

import pytest

from src.pdf_semantic_chunking.api import chunk_pdf
from src.pdf_semantic_chunking.augmentation import build_augmented_text
from src.pdf_semantic_chunking.errors import SemanticChunkingError

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "fixtures"
)

# Known production bug: PdfminerParser._process_lt_element tries to iterate
# over LTCurve objects, which are not iterable in pdfminer.six >= 20231228.
# Affects ALL tests that call chunk_pdf() on real PDF files.
LTCURVE_BUG_REASON = (
    "Known production bug in PdfminerParser._process_lt_element: "
    "'LTCurve' object is not iterable. The LTCurve branch uses "
    "'for child in lt_elem' but LTCurve objects are not iterable. "
    "See src/pdf_semantic_chunking/extraction/loader.py:75."
)


# ======================================================================
# test_semantic_chunk_pdf_api
# ======================================================================


class TestSemanticChunkPdfApi:
    """Test the chunk_pdf() API function directly on fixture PDFs."""

    @pytest.mark.asyncio
    async def test_chunk_pdf_returns_dict_with_chunks_and_stats(self):
        """chunk_pdf returns dict with 'chunks' and 'stats' keys on structured.pdf."""
        file_path = os.path.join(FIXTURE_DIR, "structured.pdf")
        result = await chunk_pdf(file_path)
        assert isinstance(result, dict)
        assert "chunks" in result
        assert "stats" in result

    @pytest.mark.asyncio
    async def test_chunks_list_is_non_empty(self):
        """chunk_pdf on structured.pdf produces at least one chunk."""
        file_path = os.path.join(FIXTURE_DIR, "structured.pdf")
        result = await chunk_pdf(file_path)
        assert len(result["chunks"]) > 0

    @pytest.mark.asyncio
    async def test_each_chunk_has_content_metadata_chunk_index(self):
        """Every chunk dict has 'content', 'metadata', and 'chunk_index' keys."""
        file_path = os.path.join(FIXTURE_DIR, "structured.pdf")
        result = await chunk_pdf(file_path)
        for chunk in result["chunks"]:
            assert "content" in chunk, "Chunk missing 'content'"
            assert "metadata" in chunk, "Chunk missing 'metadata'"
            assert "chunk_index" in chunk, "Chunk missing 'chunk_index'"
            assert isinstance(chunk["content"], str)
            assert isinstance(chunk["metadata"], dict)
            assert isinstance(chunk["chunk_index"], int)

    @pytest.mark.asyncio
    async def test_stats_has_chunk_count_total_tokens_elapsed(self):
        """Stats dict contains 'chunk_count', 'total_tokens', and 'elapsed_seconds'."""
        file_path = os.path.join(FIXTURE_DIR, "structured.pdf")
        result = await chunk_pdf(file_path)
        stats = result["stats"]
        assert "chunk_count" in stats
        assert "total_tokens" in stats
        assert "elapsed_seconds" in stats
        assert isinstance(stats["chunk_count"], int)
        assert isinstance(stats["total_tokens"], (int, float))
        assert isinstance(stats["elapsed_seconds"], (int, float))
        assert stats["chunk_count"] == len(result["chunks"])

    @pytest.mark.asyncio
    async def test_chunk_indices_are_sequential(self):
        """Chunk indices are sequential starting from 0."""
        file_path = os.path.join(FIXTURE_DIR, "structured.pdf")
        result = await chunk_pdf(file_path)
        for i, chunk in enumerate(result["chunks"]):
            assert chunk["chunk_index"] == i, (
                f"Expected index {i}, got {chunk['chunk_index']}"
            )

    @pytest.mark.asyncio
    async def test_chunk_pdf_on_unstructured_pdf(self):
        """unstructured.pdf also produces valid output."""
        file_path = os.path.join(FIXTURE_DIR, "unstructured.pdf")
        result = await chunk_pdf(file_path)
        assert "chunks" in result
        assert len(result["chunks"]) > 0
        for chunk in result["chunks"]:
            assert "content" in chunk
            assert "metadata" in chunk

    @pytest.mark.asyncio
    async def test_chunk_pdf_on_multi_column_pdf(self):
        """multi_column.pdf also produces valid output."""
        file_path = os.path.join(FIXTURE_DIR, "multi_column.pdf")
        result = await chunk_pdf(file_path)
        assert "chunks" in result
        assert len(result["chunks"]) > 0
        assert result["stats"]["chunk_count"] == len(result["chunks"])

    @pytest.mark.xfail(reason=LTCURVE_BUG_REASON)
    @pytest.mark.asyncio
    async def test_chunk_pdf_on_com_sample_pdf(self):
        """com_sample.pdf produces chunks with COM-related metadata."""
        file_path = os.path.join(FIXTURE_DIR, "com_sample.pdf")
        result = await chunk_pdf(file_path)
        assert "chunks" in result
        assert len(result["chunks"]) > 0

        # At least some chunks should have COM element types
        com_types = {"function", "property", "enum", "record", "error_code"}
        com_chunks_found = any(
            chunk.get("metadata", {}).get("element_type") in com_types
            for chunk in result["chunks"]
        )
        # com_sample.pdf should have at least some COM-type content
        assert com_chunks_found, (
            "Expected at least one COM-type chunk from com_sample.pdf"
        )


# ======================================================================
# test_build_augmented_text_integration
# ======================================================================


class TestBuildAugmentedTextIntegration:
    """Test augmentation with real pipeline output from com_sample.pdf."""

    @pytest.mark.xfail(reason=LTCURVE_BUG_REASON)
    @pytest.mark.asyncio
    async def test_com_chunk_gets_com_api_prefix(self):
        """First COM chunk from com_sample.pdf gets 'COM API' prefix via augmentation."""
        file_path = os.path.join(FIXTURE_DIR, "com_sample.pdf")
        result = await chunk_pdf(file_path)

        com_types = {"function", "property", "enum", "record", "error_code"}
        com_chunks = [
            c for c in result["chunks"]
            if c.get("metadata", {}).get("element_type") in com_types
        ]

        assert len(com_chunks) > 0, (
            "com_sample.pdf should have at least one COM-type chunk"
        )

        # Augment the first COM chunk
        com_chunk = com_chunks[0]
        augmented = build_augmented_text(
            com_chunk["content"], com_chunk["metadata"]
        )
        assert "COM" in augmented, (
            "Augmented text should contain 'COM' for COM-type chunks"
        )

    @pytest.mark.xfail(reason=LTCURVE_BUG_REASON)
    @pytest.mark.asyncio
    async def test_com_chunk_augmentation_preserves_content(self):
        """Augmentation preserves the original chunk content."""
        file_path = os.path.join(FIXTURE_DIR, "com_sample.pdf")
        result = await chunk_pdf(file_path)

        com_types = {"function", "property", "enum", "record", "error_code"}
        com_chunks = [
            c for c in result["chunks"]
            if c.get("metadata", {}).get("element_type") in com_types
        ]

        assert len(com_chunks) > 0
        com_chunk = com_chunks[0]
        augmented = build_augmented_text(
            com_chunk["content"], com_chunk["metadata"]
        )
        # Original content should be at the end of the augmented text
        assert augmented.endswith(com_chunk["content"]), (
            "Augmented text should contain original content at the end"
        )


# ======================================================================
# test_semantic_chunking_error_handling
# ======================================================================


class TestSemanticChunkingErrorHandling:
    """Error path for non-existent files."""

    @pytest.mark.asyncio
    async def test_non_existent_file_raises_error(self):
        """chunk_pdf with a non-existent file raises SemanticChunkingError."""
        fake_path = "/tmp/nonexistent_file_12345.pdf"
        with pytest.raises(SemanticChunkingError) as exc_info:
            await chunk_pdf(fake_path)

    @pytest.mark.asyncio
    async def test_error_has_to_dict_method(self):
        """SemanticChunkingError provides a to_dict() method returning a dict."""
        fake_path = "/tmp/nonexistent_file_12345.pdf"
        with pytest.raises(SemanticChunkingError) as exc_info:
            await chunk_pdf(fake_path)

        error = exc_info.value
        report = error.to_dict()
        assert isinstance(report, dict)

    @pytest.mark.asyncio
    async def test_error_to_dict_has_sanitized_fields(self):
        """to_dict() returns dict with expected sanitized fields."""
        fake_path = "/tmp/nonexistent_file_12345.pdf"
        with pytest.raises(SemanticChunkingError) as exc_info:
            await chunk_pdf(fake_path)

        report = exc_info.value.to_dict()
        assert "error" in report
        assert "stage" in report
        assert "exception" in report
        assert "context_snapshot" in report

        # file_path in context_snapshot should be basename only
        fp = report["context_snapshot"].get("file_path", "")
        assert "/" not in fp, (
            f"file_path should be basename only, got: {fp}"
        )


# ======================================================================
# test_augmentation_non_com_chunk
# ======================================================================


class TestAugmentationNonComChunk:
    """Augmentation with non-COM chunks should NOT produce 'COM API' prefix."""

    @pytest.mark.asyncio
    async def test_non_com_chunk_does_not_get_com_prefix(self):
        """Non-COM chunk from structured.pdf does NOT get 'COM API' prefix."""
        file_path = os.path.join(FIXTURE_DIR, "structured.pdf")
        result = await chunk_pdf(file_path)

        com_types = {"function", "property", "enum", "record", "error_code"}
        non_com_chunks = [
            c for c in result["chunks"]
            if c.get("metadata", {}).get("element_type") not in com_types
        ]

        assert len(non_com_chunks) > 0, (
            "structured.pdf should have at least one non-COM chunk"
        )

        non_com = non_com_chunks[0]
        augmented = build_augmented_text(
            non_com["content"], non_com["metadata"]
        )
        assert "COM API" not in augmented, (
            "Non-COM chunk should NOT contain 'COM API' prefix"
        )

    @pytest.mark.asyncio
    async def test_non_com_chunk_prefix_is_section_or_element_type(self):
        """Non-COM chunk prefix is section-based or [element_type]-based."""
        file_path = os.path.join(FIXTURE_DIR, "structured.pdf")
        result = await chunk_pdf(file_path)

        com_types = {"function", "property", "enum", "record", "error_code"}
        non_com_chunks = [
            c for c in result["chunks"]
            if c.get("metadata", {}).get("element_type") not in com_types
        ]

        assert len(non_com_chunks) > 0
        non_com = non_com_chunks[0]
        meta = non_com["metadata"]
        augmented = build_augmented_text(
            non_com["content"], meta
        )

        # If there's a section_hierarchy, we expect [Section: ...] prefix
        if meta.get("section_hierarchy"):
            assert augmented.startswith("[Section:"), (
                "Section-based chunk should have [Section: ...] prefix"
            )
        elif meta.get("element_type"):
            assert augmented.startswith(f"[{meta['element_type']}]") or augmented == non_com["content"], (
                "Non-COM chunk should have element-type prefix or raw content"
            )

    @pytest.mark.asyncio
    async def test_all_non_com_chunks_from_structured_no_com_api(self):
        """No chunk from structured.pdf gets 'COM API' in its augmented form."""
        file_path = os.path.join(FIXTURE_DIR, "structured.pdf")
        result = await chunk_pdf(file_path)

        for chunk in result["chunks"]:
            augmented = build_augmented_text(
                chunk["content"], chunk["metadata"]
            )
            assert "COM API" not in augmented, (
                f"Chunk {chunk['chunk_index']} unexpectedly got 'COM API' prefix"
            )


# ======================================================================
# test_semantic_error_to_dict_sanitization
# ======================================================================


class TestSemanticErrorToDictSanitization:
    """Verify error paths are sanitized via to_dict()."""

    def test_file_path_in_context_snapshot_is_basename(self):
        """file_path in context_snapshot is basename only (no directory)."""
        error = SemanticChunkingError(
            error="TestError",
            stage="test",
            context_snapshot={"file_path": "/some/deep/path/file.pdf"},
        )
        report = error.to_dict()
        fp = report["context_snapshot"]["file_path"]
        assert "/" not in fp, f"file_path should be basename, got: {fp}"
        assert fp == "file.pdf"

    def test_exception_field_truncated_to_max_200_chars(self):
        """exception field in to_dict() is truncated to at most 200 characters."""
        long_exception = "x" * 1000
        error = SemanticChunkingError(
            error="TestError",
            stage="test",
            exception=long_exception,
        )
        report = error.to_dict()
        assert len(report["exception"]) <= 200

    def test_multiple_paths_in_context_are_sanitized(self):
        """Multiple path-like values in context_snapshot are sanitized."""
        error = SemanticChunkingError(
            error="MultiPathError",
            stage="test",
            context_snapshot={
                "file_path": "/a/b/c/doc.pdf",
                "source": "/var/data/input.txt",
                "normal_key": "just a string",
            },
        )
        report = error.to_dict()
        assert report["context_snapshot"]["file_path"] == "doc.pdf"
        assert report["context_snapshot"]["source"] == "input.txt"
        assert report["context_snapshot"]["normal_key"] == "just a string"

    @pytest.mark.xfail(
        sys.platform != "win32",
        strict=True,
        reason=(
            "os.path.basename() is platform-specific; on macOS/Linux backslashes "
            "are not path separators, so the full string is returned unchanged"
        ),
    )
    def test_windows_path_is_sanitized(self):
        """Windows-style backslash paths are also sanitized to basename.

        Note: This only works on Windows where ``os.path.basename`` recognizes
        backslash as a separator.
        """
        error = SemanticChunkingError(
            error="WinPathError",
            stage="test",
            context_snapshot={"file_path": "C:\\Users\\test\\doc.pdf"},
        )
        report = error.to_dict()
        assert report["context_snapshot"]["file_path"] == "doc.pdf"

    def test_exact_200_char_exception_not_truncated(self):
        """A 200-character exception is kept intact (not truncated)."""
        exact_200 = "a" * 200
        error = SemanticChunkingError(
            error="Exact200",
            stage="test",
            exception=exact_200,
        )
        report = error.to_dict()
        assert report["exception"] == exact_200
        assert len(report["exception"]) == 200

    def test_short_exception_not_truncated(self):
        """A short exception string is unchanged."""
        error = SemanticChunkingError(
            error="ShortError",
            stage="test",
            exception="File not found",
        )
        report = error.to_dict()
        assert report["exception"] == "File not found"

    def test_empty_exception_is_empty_string(self):
        """Empty exception string remains empty in to_dict()."""
        error = SemanticChunkingError(
            error="NoException",
            stage="test",
            exception="",
        )
        report = error.to_dict()
        assert report["exception"] == ""

    def test_to_dict_contains_error_stage_page(self):
        """to_dict() includes error, stage, page, exception, and context_snapshot keys."""
        error = SemanticChunkingError(
            error="MyError",
            stage="extraction",
            page=3,
            exception="Something went wrong",
        )
        report = error.to_dict()
        assert report["error"] == "MyError"
        assert report["stage"] == "extraction"
        assert report["page"] == 3
        assert report["exception"] == "Something went wrong"
        assert isinstance(report["context_snapshot"], dict)

    def test_none_page_returns_none(self):
        """When page is None, to_dict() preserves None."""
        error = SemanticChunkingError(
            error="NoPage",
            stage="test",
        )
        report = error.to_dict()
        assert report["page"] is None
