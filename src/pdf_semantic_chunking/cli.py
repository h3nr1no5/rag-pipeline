import argparse
import json
import sys
import time
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def build_pipeline(kwargs: dict):
    from .pipeline.orchestrator import PipelineOrchestrator
    from .extraction.loader import PdfminerParser
    from .enrichment.enricher import COMEnricher
    from .detection.boundaries import BoundaryDetector
    from .chunking.assembler import ChunkAssembler
    from .chunking.metadata import MetadataEnricher

    class ExtractionStage:
        async def process(self, ctx):
            parser = PdfminerParser()
            try:
                ctx.element_tree = parser.parse(ctx.file_path)
                ctx.parser_type = "pdfminer"
            except Exception:
                logger.warning("pdfminer failed, falling back to fitz")
                raise
            return ctx

    class EnrichmentStage:
        async def process(self, ctx):
            enricher = COMEnricher()
            ctx.enriched_tree = enricher.enrich(ctx.element_tree)
            return ctx

    class BoundaryStage:
        async def process(self, ctx):
            detector = BoundaryDetector()
            tree = ctx.enriched_tree or ctx.element_tree
            ctx.boundaries = detector.detect(tree)
            return ctx

    class AssemblyStage:
        async def process(self, ctx):
            assembler = ChunkAssembler(
                max_tokens=kwargs.get("chunk_size", 800),
                chunk_overlap=kwargs.get("chunk_overlap", 80),
            )
            tree = ctx.enriched_tree or ctx.element_tree
            ctx.chunks = assembler.assemble(tree, ctx.boundaries)
            return ctx

    class MetadataStage:
        async def process(self, ctx):
            enricher = MetadataEnricher()
            ctx.chunks = enricher.enrich(ctx.chunks, ctx.file_path)
            return ctx

    return PipelineOrchestrator([
        ExtractionStage(),
        EnrichmentStage(),
        BoundaryStage(),
        AssemblyStage(),
        MetadataStage(),
    ])


async def chunk_pdf_async(file_path: str, **kwargs) -> dict:
    from .pipeline.context import PipelineContext
    from .errors import SemanticChunkingError

    pipeline = build_pipeline(kwargs)
    ctx = PipelineContext(file_path=file_path)
    start = time.time()

    try:
        ctx = await pipeline.run(ctx)
    except SemanticChunkingError:
        raise
    except Exception as e:
        raise SemanticChunkingError(
            error="PipelineExecutionError",
            stage="pipeline",
            exception=str(e),
            context_snapshot={"file_path": file_path},
        )

    elapsed = time.time() - start
    chunks = []
    for c in ctx.chunks:
        chunks.append({
            "content": c.content,
            "metadata": c.metadata,
            "chunk_index": c.chunk_index,
        })

    total_tokens = sum(c.metadata.get("token_count", 0) for c in ctx.chunks)
    stats = {
        "total_chars": sum(len(c.content) for c in ctx.chunks),
        "chunk_count": len(ctx.chunks),
        "total_tokens": total_tokens,
        "elapsed_seconds": round(elapsed, 3),
        "stage_timing": ctx.stats.get("stage_timing", {}),
        "element_types": {},
        "validation": ctx.stats.get("validation", {}),
        "effective_chunk_size": kwargs.get("chunk_size", 800),
        "effective_chunk_overlap": kwargs.get("chunk_overlap", 80),
    }

    from collections import Counter
    type_counts = Counter(
        c.metadata.get("element_type", "mixed") for c in ctx.chunks
    )
    stats["element_types"] = dict(type_counts)

    return {"chunks": chunks, "stats": stats}


def main():
    parser = argparse.ArgumentParser(description="Semantic chunking for PDF documents")
    parser.add_argument("file_path", help="Path to the PDF file")
    parser.add_argument("--chunk-size", type=int, default=800, help="Maximum chunk size in tokens")
    parser.add_argument("--chunk-overlap", type=int, default=80, help="Overlap between chunks in tokens")
    # Old aliases (backward compat)
    parser.add_argument("--min-chunk-size", type=int, help="[DEPRECATED] Use --chunk-size instead")
    parser.add_argument("--max-chunk-size", type=int, help="[DEPRECATED] Use --chunk-size instead")
    parser.add_argument("--overlap", type=int, help="[DEPRECATED] Use --chunk-overlap instead")
    parser.add_argument("--format", choices=["jsonl", "json"], default="jsonl", help="Output format")
    args = parser.parse_args()

    import asyncio

    chunk_size = args.chunk_size
    if args.max_chunk_size is not None:
        chunk_size = args.max_chunk_size  # --max-chunk-size is alias for --chunk-size
    chunk_overlap = args.chunk_overlap
    if args.overlap is not None:
        chunk_overlap = args.overlap

    try:
        result = asyncio.run(chunk_pdf_async(
            args.file_path,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ))

        if args.format == "jsonl":
            for chunk in result["chunks"]:
                sys.stdout.write(json.dumps(chunk) + "\n")
        else:
            sys.stdout.write(json.dumps(result, indent=2) + "\n")

        stats = result["stats"]
        print(
            f"Processed: {stats['total_chars']} chars → {stats['chunk_count']} chunks "
            f"({len(stats.get('element_types', {}))} types) in {stats['elapsed_seconds']}s",
            file=sys.stderr,
        )
    except Exception as e:
        error_report = {
            "error": type(e).__name__,
            "stage": "cli",
            "page": None,
            "exception": str(e),
            "context_snapshot": {"file_path": args.file_path},
            "traceback_summary": str(e),
        }
        print(json.dumps(error_report), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
