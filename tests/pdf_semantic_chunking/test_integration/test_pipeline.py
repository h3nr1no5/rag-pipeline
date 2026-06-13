"""Integration tests for the full semantic chunking pipeline.

Tests exercise the complete pipeline end-to-end using fixture PDFs.
Pipeline stages are defined inline (mirroring the pattern in
``cli.py``) so the test reproduces the exact same pipeline topology
used in production.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pdf_semantic_chunking.chunking.assembler import ChunkAssembler
from src.pdf_semantic_chunking.chunking.metadata import MetadataEnricher
from src.pdf_semantic_chunking.detection.boundaries import BoundaryDetector
from src.pdf_semantic_chunking.enrichment.enricher import COMEnricher
from src.pdf_semantic_chunking.errors import SemanticChunkingError
from src.pdf_semantic_chunking.extraction.loader import PdfminerParser
from src.pdf_semantic_chunking.extraction.model import DocumentHierarchy
from src.pdf_semantic_chunking.pipeline.context import ChunkData, PipelineContext
from src.pdf_semantic_chunking.pipeline.orchestrator import PipelineOrchestrator

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Pipeline stage classes  (mirroring cli.py / build_pipeline)
# ---------------------------------------------------------------------------


class ExtractionStage:
    """Parse the PDF into a DocumentHierarchy using PdfminerParser."""

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        parser = PdfminerParser()
        ctx.element_tree = parser.parse(ctx.file_path)
        ctx.parser_type = "pdfminer"
        return ctx


class EnrichmentStage:
    """Enrich the element tree with COM-specific metadata."""

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        enricher = COMEnricher()
        ctx.enriched_tree = enricher.enrich(ctx.element_tree)
        return ctx


class BoundaryStage:
    """Detect semantic boundaries — headings, code blocks, tables, signatures."""

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        detector = BoundaryDetector()
        tree = ctx.enriched_tree or ctx.element_tree
        ctx.boundaries = detector.detect(tree)
        return ctx


class AssemblyStage:
    """Assemble elements into chunks based on detected boundaries."""

    def __init__(
        self,
        min_tokens: int = 200,
        max_tokens: int = 800,
        overlap_ratio: float = 0.10,
    ):
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.overlap_ratio = overlap_ratio

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        assembler = ChunkAssembler(
            min_tokens=self.min_tokens,
            max_tokens=self.max_tokens,
            overlap_ratio=self.overlap_ratio,
        )
        tree = ctx.enriched_tree or ctx.element_tree
        ctx.chunks = assembler.assemble(tree, ctx.boundaries)
        return ctx


class MetadataStage:
    """Attach source-document metadata to every chunk."""

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        enricher = MetadataEnricher()
        ctx.chunks = enricher.enrich(ctx.chunks, ctx.file_path)
        return ctx


# ---------------------------------------------------------------------------
# Pipeline builder helper
# ---------------------------------------------------------------------------


def build_pipeline(
    min_chunk_size: int = 200,
    max_chunk_size: int = 800,
    overlap_ratio: float = 0.10,
) -> PipelineOrchestrator:
    """Build the standard 5-stage pipeline matching ``cli.py``'s topology.

    Default parameters match the CLI defaults:
    * min_chunk_size  — 200 tokens
    * max_chunk_size  — 800 tokens
    * overlap_ratio   — 0.10 (10 %)
    """
    return PipelineOrchestrator([
        ExtractionStage(),
        EnrichmentStage(),
        BoundaryStage(),
        AssemblyStage(
            min_tokens=min_chunk_size,
            max_tokens=max_chunk_size,
            overlap_ratio=overlap_ratio,
        ),
        MetadataStage(),
    ])


# ======================================================================
#  Tests — structured.pdf
# ======================================================================


class TestStructuredPdfPipeline:
    """Full pipeline on ``structured.pdf`` — headings, code blocks, tables."""

    FIXTURE = str(FIXTURES_DIR / "structured.pdf")

    @pytest.mark.asyncio
    async def test_element_tree_populated(self):
        """The element tree is built from the parsed PDF."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)

        assert ctx.element_tree is not None
        assert ctx.element_tree.root is not None
        # The root should contain at least one child page element
        assert len(ctx.element_tree.root.children) > 0

    @pytest.mark.asyncio
    async def test_chunks_non_empty(self):
        """At least one chunk is produced for a structured PDF."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)

        assert len(ctx.chunks) > 0, "Expected at least one chunk"

    @pytest.mark.asyncio
    async def test_chunk_structure(self):
        """Every chunk has the expected fields with correct types."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)

        for chunk in ctx.chunks:
            assert isinstance(chunk.content, str), "chunk.content must be str"
            assert len(chunk.content) > 0, "chunk.content must be non-empty"
            assert isinstance(chunk.metadata, dict), "chunk.metadata must be dict"
            assert isinstance(chunk.chunk_index, int), "chunk.chunk_index must be int"

    @pytest.mark.asyncio
    async def test_chunk_indices_sequential(self):
        """Chunk indices run sequentially from 0."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)

        indices = [c.chunk_index for c in ctx.chunks]
        assert indices == list(range(len(ctx.chunks))), (
            f"Chunk indices must be sequential 0..{len(ctx.chunks) - 1}, "
            f"got {indices}"
        )

    @pytest.mark.asyncio
    async def test_token_count_in_metadata(self):
        """At least some chunks contain *token_count* in their metadata."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)

        chunks_with_tc = [c for c in ctx.chunks if "token_count" in c.metadata]
        assert len(chunks_with_tc) > 0, (
            "Expected at least one chunk with token_count in metadata"
        )

    @pytest.mark.asyncio
    async def test_stage_timing_recorded(self):
        """The pipeline records timing for each of the five stages."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)

        stage_timing = ctx.stats.get("stage_timing", {})
        expected_stages = [
            "ExtractionStage",
            "EnrichmentStage",
            "BoundaryStage",
            "AssemblyStage",
            "MetadataStage",
        ]
        for name in expected_stages:
            assert name in stage_timing, (
                f"Missing stage_timing entry for {name}. "
                f"Got keys: {list(stage_timing)}"
            )
            elapsed = stage_timing[name]
            assert isinstance(elapsed, (int, float)), (
                f"stage_timing[{name}] must be numeric, got {type(elapsed)}"
            )
            assert elapsed >= 0, (
                f"stage_timing[{name}] must be non-negative, got {elapsed}"
            )


# ======================================================================
#  Tests — unstructured.pdf
# ======================================================================


class TestUnstructuredPdfPipeline:
    """Full pipeline on ``unstructured.pdf`` — plain prose, no headings."""

    FIXTURE = str(FIXTURES_DIR / "unstructured.pdf")

    @pytest.mark.asyncio
    async def test_pipeline_completes(self):
        """Pipeline runs without error on a narrative-only PDF."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)
        assert ctx is not None

    @pytest.mark.asyncio
    async def test_at_least_one_chunk(self):
        """Even a simple prose document produces at least one chunk."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)
        assert len(ctx.chunks) >= 1

    @pytest.mark.asyncio
    async def test_not_a_com_document(self):
        """A narrative PDF does NOT produce COM-style element types."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)

        com_types = {"function", "property", "enum", "record", "error_code"}
        for chunk in ctx.chunks:
            et = chunk.metadata.get("element_type", "")
            msg = (
                f"Unexpected COM element_type '{et}' found in chunk "
                f"{chunk.chunk_index} of unstructured PDF"
            )
            # element_type can legitimately be "mixed" or absent, but not
            # a specific COM type like "function" or "enum".
            assert et not in com_types or et == "mixed", msg

    @pytest.mark.asyncio
    async def test_parser_is_pdfminer(self):
        """The parser type is recorded as ``pdfminer``."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)
        assert ctx.parser_type == "pdfminer"


# ======================================================================
#  Tests — com_sample.pdf
# ======================================================================


class TestComSamplePdfPipeline:
    """Full pipeline on ``com_sample.pdf`` — C# COM interop declarations."""

    FIXTURE = str(FIXTURES_DIR / "com_sample.pdf")

    @pytest.mark.asyncio
    async def test_pipeline_completes(self):
        """Pipeline runs without error on a COM-interop PDF."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)
        assert ctx is not None

    @pytest.mark.asyncio
    async def test_at_least_one_chunk(self):
        """The COM sample produces at least one chunk."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)
        assert len(ctx.chunks) >= 1

    @pytest.mark.asyncio
    async def test_com_enrichment_adds_element_types(self):
        """After COM enrichment some chunks have a COM element type.

        The ``com_sample.pdf`` contains ``[ComImport]``, ``[Guid(...)]``,
        interface declarations and enum definitions — the enricher should
        classify at least one chunk as ``function``, ``enum``, or similar.
        """
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)

        # Every chunk should have element_type in metadata
        for chunk in ctx.chunks:
            assert "element_type" in chunk.metadata, (
                f"Chunk {chunk.chunk_index} is missing element_type metadata"
            )

        com_types = {"function", "property", "enum", "record", "error_code"}
        seen_types: set[str] = set()

        for chunk in ctx.chunks:
            et = chunk.metadata.get("element_type")
            if et:
                seen_types.add(et)

        # At least one specific COM type, OR element_name presence proves
        # enrichment happened (the assembly stage may merge multiple COM
        # elements into a single chunk, producing "mixed").
        has_com_types = bool(com_types & seen_types)
        has_element_names = any(
            c.metadata.get("element_name") for c in ctx.chunks
        )
        assert has_com_types or has_element_names, (
            f"No COM element types found. Seen element_types: {seen_types}. "
            f"No element_name found either."
        )

    @pytest.mark.asyncio
    async def test_com_chunks_have_element_name(self):
        """COM-derived chunks carry an *element_name* in metadata."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path=self.FIXTURE)
        ctx = await pipeline.run(ctx)

        chunks_with_name = [
            c for c in ctx.chunks
            if c.metadata.get("element_name")
        ]
        assert len(chunks_with_name) > 0, (
            "Expected at least one chunk with element_name from COM enrichment"
        )


# ======================================================================
#  Tests — error handling
# ======================================================================


class TestPipelineEmptyInput:
    """Pipeline error handling for invalid inputs."""

    @pytest.mark.asyncio
    async def test_nonexistent_file_raises_semantic_error(self):
        """A non-existent file raises SemanticChunkingError."""
        pipeline = build_pipeline()
        ctx = PipelineContext(file_path="/nonexistent/path/to/file.pdf")

        with pytest.raises(SemanticChunkingError) as exc_info:
            await pipeline.run(ctx)

        # The error should reference the ExtractionStage
        assert "ExtractionStage" in str(exc_info.value.error), (
            f"Expected ExtractionStage in error, got: {exc_info.value.error}"
        )
