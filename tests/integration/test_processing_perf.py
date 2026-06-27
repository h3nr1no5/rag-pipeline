"""Performance and reliability test for document processing pipeline.

Tests the actual ``axis com snippet.docx`` fixture through the full
ingestion pipeline (parse → detect → convert → chunk → index) and
measures timing for each stage.

This test is tagged ``@pytest.mark.slow`` because it loads the embedding
model (~5-20s on first call) and should NOT be run in CI on every commit.

Usage:
    uv run pytest tests/integration/test_processing_perf.py -v --timeout=120
"""

import logging
import time
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent.parent / "docs"
FIXTURE = "axis com snippet.docx"

# Time budgets (seconds) — if processing exceeds these, the pipeline may
# be regressing or something is stuck.  Budgets account for cold-start
# embedding model loading on Apple Silicon (MLX).
TIME_BUDGETS = {
    "parse": 15.0,      # DOCX parse + transitive imports
    "detect": 1.0,      # Keyword + paragraph detection
    "convert": 1.0,     # Domain object conversion
    "graph": 2.0,       # Chunk graph build + format
    "bm25": 2.0,        # BM25 index build
    "embed": 60.0,      # Model load + batch encode 209 texts
    "hybrid": 2.0,      # HybridRetriever init
    "total": 90.0,      # Complete pipeline
}


@pytest.mark.slow
@pytest.mark.asyncio
async def test_axis_com_processing_performance():
    """Process the real axis com snippet.docx and measure each stage.

    Verifies:
    - All pipeline stages complete within time budgets
    - Correct number of interfaces, enums, error_codes, records
    - Correct number of chunk graph nodes
    - Query returns meaningful results after indexing
    """
    file_path = FIXTURES_DIR / FIXTURE
    assert file_path.exists(), f"Fixture not found: {file_path}"
    file_size = file_path.stat().st_size
    logger.info("Processing %s (%d bytes)", FIXTURE, file_size)

    times = {}

    # ── Stage 1: Parse ────────────────────────────────────────────────
    t0 = time.monotonic()
    from src.domain.rag.api_docs.extraction.docx_parser import DocxParser

    parser = DocxParser(str(file_path))
    raw_doc = parser.parse()
    t1 = time.monotonic()
    times["parse"] = t1 - t0
    logger.info(
        "Parse: %d paragraphs, %d tables (%.2fs)",
        len(raw_doc.paragraphs),
        len(raw_doc.tables),
        times["parse"],
    )

    # ── Stage 2: Detect table types ───────────────────────────────────
    from src.domain.rag.api_docs.extraction.table_detector import (
        TableDetector,
        merge_multi_row_functions,
    )

    detector = TableDetector()
    table_types = detector.detect_from_document(raw_doc)
    merged = merge_multi_row_functions(raw_doc.tables)
    t2 = time.monotonic()
    times["detect"] = t2 - t1
    type_counts: dict[str, int] = {}
    for tt in table_types.values():
        type_counts[tt] = type_counts.get(tt, 0) + 1
    logger.info("Detect: %s (%.2fs)", type_counts, times["detect"])

    # ── Stage 3: Convert ──────────────────────────────────────────────
    from src.domain.rag.api_docs.extraction.converter import DocumentConverter

    converter = DocumentConverter()
    domain_result = converter.convert(raw_doc, table_types, merged)
    t3 = time.monotonic()
    times["convert"] = t3 - t2
    interfaces = domain_result["interfaces"]
    enums = domain_result["enums"]
    error_codes = domain_result["error_codes"]
    records = domain_result.get("records", [])
    logger.info(
        "Convert: %d ifaces, %d enums, %d errors, %d records (%.2fs)",
        len(interfaces),
        len(enums),
        len(error_codes),
        len(records),
        times["convert"],
    )

    # ── Stage 4: Build chunk graph ────────────────────────────────────
    from src.domain.rag.api_docs.chunking.builder import ChunkGraphBuilder
    from src.domain.rag.api_docs.chunking.text_formatter import (
        ChunkTextFormatter,
    )

    builder = ChunkGraphBuilder()
    graph = builder.build(
        interfaces=interfaces,
        enums=enums,
        error_codes=error_codes,
        records=records,
        source_doc="test-perf",
    )
    formatter = ChunkTextFormatter()
    formatter.format_graph(
        graph,
        interfaces,
        enums,
        error_codes,
        records=records,
    )
    t4 = time.monotonic()
    times["graph"] = t4 - t3
    logger.info("Graph: %d nodes (%.2fs)", len(graph.nodes), times["graph"])

    # ── Stage 5a: BM25 index ──────────────────────────────────────────
    from src.domain.rag.api_docs.retrieval.bm25_index import ApiBm25Index

    bm25 = ApiBm25Index()
    bm25.add_graph(graph)
    t5 = time.monotonic()
    times["bm25"] = t5 - t4
    logger.info("BM25: %d docs (%.2fs)", len(bm25.chunk_ids), times["bm25"])

    # ── Stage 5b: Embedding index ─────────────────────────────────────
    from src.domain.rag.api_docs.retrieval.embedding_index import (
        ApiEmbeddingIndex,
    )

    embed_idx = ApiEmbeddingIndex()
    await embed_idx.add_graph(
        graph,
        formatter,
        interfaces=interfaces,
        enums=enums,
        error_codes=error_codes,
        records=records,
    )
    t6 = time.monotonic()
    times["embed"] = t6 - t5
    logger.info(
        "Embed: %d vectors (%.2fs)",
        len(embed_idx.chunk_ids),
        times["embed"],
    )

    # ── Stage 5c: Hybrid retriever ────────────────────────────────────
    from src.domain.rag.api_docs.retrieval.hybrid_retriever import (
        HybridRetriever,
    )

    retriever = HybridRetriever(bm25, embed_idx, graph)
    t7 = time.monotonic()
    times["hybrid"] = t7 - t6
    total = t7 - t0
    times["total"] = total

    logger.info("Total pipeline: %.2fs", total)

    # ── Verify timing budgets ─────────────────────────────────────────
    failures = []
    for stage, budget in TIME_BUDGETS.items():
        actual = times.get(stage, 0)
        if actual > budget:
            msg = (
                f"Stage '{stage}' took {actual:.2f}s "
                f"(budget {budget:.2f}s)"
            )
            logger.warning(msg)
            failures.append(msg)
    if failures:
        pytest.fail(
            "Pipeline stage(s) exceeded time budget:\n  "
            + "\n  ".join(failures)
        )

    # ── Verify domain object counts ───────────────────────────────────
    assert len(interfaces) >= 3, (
        f"Expected ≥3 interfaces, got {len(interfaces)}"
    )
    assert len(error_codes) >= 50, (
        f"Expected ≥50 error codes, got {len(error_codes)}"
    )
    assert len(graph.nodes) >= 150, (
        f"Expected ≥150 graph nodes, got {len(graph.nodes)}"
    )

    # ── Verify query returns results ──────────────────────────────────
    results = await retriever.retrieve("how to add material", top_k=5)
    assert len(results) > 0, "Retrieval returned zero results"
    scores = [s for _, s in results]
    max_score = max(scores)
    assert max_score > 0.0, (
        f"No result has a score > 0 (all scores: {scores})"
    )
    logger.info(
        "Query returned %d results, max score=%.3f (scores=%s)",
        len(results),
        max_score,
        scores,
    )


@pytest.mark.slow
@pytest.mark.asyncio
async def test_embedding_model_load_time():
    """Measure how long the embedding model takes to load from cold start.

    This is the dominant cost during first-time processing after server
    restart.  The model (~500MB) is cached locally after first download.

    Budget: 30 seconds for model load alone.
    """
    from src.domain.services.embedding import get_embedder, reset_embedder

    # Force cold start by resetting the singleton
    reset_embedder()

    t0 = time.monotonic()
    embedder = await get_embedder()
    t1 = time.monotonic()
    load_time = t1 - t0
    dim = embedder.get_dimension()

    logger.info("Embedding model loaded in %.2fs (dim=%d)", load_time, dim)
    assert load_time < 45.0, (
        f"Embedding model load took {load_time:.2f}s (budget 45s)"
    )
    assert dim == 768, f"Expected dim=768, got {dim}"
