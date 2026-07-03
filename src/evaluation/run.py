"""RAG evaluation pipeline orchestrator.

Usage:
    python -m src.evaluation.run \\
        --backends cosine,langchain,llamaindex \\
        --dataset tests/evaluation/eval_dataset.json
"""
import argparse
import asyncio
import io
import logging
import os
import time
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.api.main import app
from src.evaluation.dataset import load_dataset
from src.evaluation.metrics import (
    faithfulness,
    keyword_recall,
    mrr,
    precision_at_k,
    recall_at_k,
)
from src.evaluation.report import write_json_report, write_markdown_report
from src.infrastructure.database import async_session_maker
from src.infrastructure.database.models import Chunk

logger = logging.getLogger(__name__)


async def _auth_and_get_client() -> AsyncClient:
    """Create an authenticated HTTP client using in-process ASGI transport."""
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    test_email = f"eval_{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/v1/auth/signup",
        json={"email": test_email, "password": "evalpassword123"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": test_email, "password": "evalpassword123"},
    )
    token = login_resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


async def _upload_and_wait(
    client: AsyncClient, doc_path: str, filename: str
) -> str:
    """Upload a document via the API and poll until processing completes.

    Args:
        client: Authenticated HTTP client
        doc_path: Path to the document file on disk
        filename: Display filename for the upload

    Returns:
        Document ID (str) of the processed document

    Raises:
        RuntimeError: If processing fails or times out
    """
    with open(doc_path, "rb") as f:
        file_content = f.read()

    files = {"file": (filename, io.BytesIO(file_content), "text/plain")}
    data = {"strategy_id": "recursive"}

    upload_resp = await client.post("/api/v1/documents", files=files, data=data)
    upload_resp.raise_for_status()
    doc_id = upload_resp.json()["id"]

    # Poll until processing completes
    poll_interval = 0.2
    timeout = 60.0
    start = time.monotonic()

    while True:
        status_resp = await client.get(f"/api/v1/documents/{doc_id}/status")
        if status_resp.status_code == 200:
            status = status_resp.json()
            if status["status"] == "completed":
                # Verify chunks are actually available
                chunks_resp = await client.get(
                    f"/api/v1/documents/{doc_id}/chunks?limit=1"
                )
                if chunks_resp.status_code == 200:
                    chunks_data = chunks_resp.json()
                    if len(chunks_data.get("chunks", [])) > 0:
                        return doc_id
            elif status["status"] == "failed":
                raise RuntimeError(
                    f"Document processing failed: {status.get('error_message', 'Unknown error')}"
                )

        if time.monotonic() - start > timeout:
            raise RuntimeError(f"Document processing timed out after {timeout}s")

        await asyncio.sleep(poll_interval)


async def _get_relevant_chunk_ids(
    document_id: str, expected_sources: list[str]
) -> set[str]:
    """Find chunk IDs whose content contains any of the expected_source texts.

    Queries the database directly to get all chunk content for the document
    and performs substring matching against expected_sources.

    Args:
        document_id: The document's UUID
        expected_sources: List of source text snippets to match

    Returns:
        Set of chunk IDs that contain at least one expected_source
    """
    relevant: set[str] = set()

    async with async_session_maker() as session:
        result = await session.execute(
            select(Chunk).where(Chunk.document_id == document_id)
        )
        chunks = result.scalars().all()

        for chunk in chunks:
            for source in expected_sources:
                if source in chunk.content:
                    relevant.add(chunk.id)
                    break  # One match per chunk is enough

    return relevant


async def _query_backend(
    client: AsyncClient,
    question: str,
    document_ids: list[str],
    backend: str,
    top_k: int,
    temperature: float,
) -> dict:
    """Query a specific RAG backend and return the parsed response.

    Args:
        client: Authenticated HTTP client
        question: The question text
        document_ids: List of document UUIDs to query against
        backend: Backend name ('cosine', 'langchain', or 'llamaindex')
        top_k: Number of chunks to retrieve
        temperature: LLM temperature

    Returns:
        Dict with 'answer', 'sources', 'latency_ms' keys

    Raises:
        RuntimeError: If the backend query fails
    """
    endpoint_map = {
        "cosine": "/api/v1/query",
        "langchain": "/api/v1/query/langchain",
        "llamaindex": "/api/v1/query/llamaindex",
    }

    endpoint = endpoint_map.get(backend)
    if endpoint is None:
        raise ValueError(f"Unknown backend: {backend}")

    payload = {
        "question": question,
        "document_ids": document_ids,
        "top_k": top_k,
        "temperature": temperature,
    }

    response = await client.post(endpoint, json=payload)

    if response.status_code == 404:
        # No content found - valid response, just no results
        return {"answer": "", "sources": [], "latency_ms": 0}

    response.raise_for_status()
    data = response.json()

    return {
        "answer": data.get("answer", ""),
        "sources": data.get("sources", []),
        "latency_ms": data.get("latency_ms", 0),
    }


def _compute_retrieval_metrics(
    retrieved_chunk_ids: list[str],
    relevant_chunk_ids: set[str],
    top_k: int,
) -> dict:
    """Compute precision@k, recall@k, and MRR.

    Args:
        retrieved_chunk_ids: Ordered list of retrieved chunk IDs
        relevant_chunk_ids: Set of ground-truth relevant chunk IDs
        top_k: k value for precision@k and recall@k

    Returns:
        Dict with precision_at_k, recall_at_k, mrr
    """
    return {
        "precision_at_k": precision_at_k(relevant_chunk_ids, retrieved_chunk_ids, top_k),
        "recall_at_k": recall_at_k(relevant_chunk_ids, retrieved_chunk_ids, top_k),
        "mrr": mrr(relevant_chunk_ids, retrieved_chunk_ids),
    }


async def main():
    """Run the evaluation pipeline."""
    parser = argparse.ArgumentParser(description="RAG Evaluation Pipeline")
    parser.add_argument(
        "--backends",
        default="cosine,langchain,llamaindex",
        help="Comma-separated list of backends to evaluate (default: all)",
    )
    parser.add_argument(
        "--dataset",
        default="tests/evaluation/eval_dataset.json",
        help="Path to the evaluation dataset JSON file",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=4,
        help="Number of chunks to retrieve per query (default: 4)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="LLM temperature (default: 0.1)",
    )
    parser.add_argument(
        "--output",
        default="data/eval_reports",
        help="Directory for evaluation reports (default: data/eval_reports)",
    )

    args = parser.parse_args()
    backends = [b.strip() for b in args.backends.split(",")]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    logger.info("=" * 60)
    logger.info("RAG Evaluation Pipeline")
    logger.info(f"Dataset: {args.dataset}")
    logger.info(f"Backends: {backends}")
    logger.info(f"Top-K: {args.top_k}")
    logger.info("=" * 60)

    # Load dataset
    dataset = load_dataset(args.dataset)
    logger.info(
        f"Loaded dataset: {dataset.version} with {len(dataset.questions)} questions"
    )

    # Authenticate
    client = await _auth_and_get_client()
    logger.info("Authenticated evaluation client")

    # Upload documents and collect document IDs
    doc_id_map: dict[str, str] = {}  # filename -> document_id

    for doc in dataset.documents:
        logger.info(f"Uploading document: {doc.filename}")
        doc_id = await _upload_and_wait(client, doc.path, doc.filename)
        doc_id_map[doc.filename] = doc_id
        logger.info(f"Document {doc.filename} -> {doc_id}")

    # Build relevant chunk ID sets per question (content-matching)
    question_relevant: dict[str, set[str]] = {}
    for q in dataset.questions:
        doc_id = doc_id_map.get(q.document)
        if doc_id:
            relevant = await _get_relevant_chunk_ids(doc_id, q.expected_sources)
            question_relevant[q.id] = relevant
            logger.info(f"Question {q.id}: {len(relevant)} relevant chunks found")

    # Run evaluation for each question x backend
    results: dict[str, dict] = {}

    for q in dataset.questions:
        doc_ids = [doc_id_map[q.document]]
        results[q.id] = {}

        for backend in backends:
            logger.info(f"Querying {backend} for question {q.id}...")

            try:
                resp = await _query_backend(
                    client,
                    q.question,
                    doc_ids,
                    backend,
                    args.top_k,
                    args.temperature,
                )
            except Exception as e:
                logger.error(f"Query failed for {backend}/{q.id}: {e}")
                results[q.id][backend] = {"error": str(e)}
                continue

            answer = resp["answer"]
            sources = resp["sources"]
            latency_ms = resp["latency_ms"]

            # Extract chunk IDs from retrieved sources
            retrieved_chunk_ids = [s.get("chunk_id", "") for s in sources]

            # Compute retrieval metrics
            relevant = question_relevant.get(q.id, set())
            retrieval = _compute_retrieval_metrics(
                retrieved_chunk_ids, relevant, args.top_k
            )

            # Compute answer quality metrics
            source_texts = [s.get("content", "") for s in sources]

            kw_recall = keyword_recall(answer, q.expected_keywords)

            f_score = await faithfulness(answer, source_texts)

            has_min_length = len(answer) >= q.min_answer_length

            results[q.id][backend] = {
                **retrieval,
                "faithfulness": f_score,
                "keyword_recall": kw_recall,
                "has_min_length": has_min_length,
                "latency_ms": latency_ms,
            }

    # Compute per-backend summary
    summary: dict[str, dict] = {}
    for backend in backends:
        backend_results = []
        for q in dataset.questions:
            if backend in results.get(q.id, {}):
                br = results[q.id][backend]
                if "error" not in br:
                    backend_results.append(br)

        if backend_results:
            summary[backend] = {}
            # Collect all metric keys
            metric_keys = set()
            for br in backend_results:
                metric_keys.update(br.keys())

            for key in sorted(metric_keys):
                values = [
                    br[key]
                    for br in backend_results
                    if key in br and isinstance(br[key], (int, float))
                ]
                if values:
                    summary[backend][f"avg_{key}"] = sum(values) / len(values)
                    summary[backend][f"min_{key}"] = min(values)
                    summary[backend][f"max_{key}"] = max(values)

    # Build report
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dataset_version": dataset.version,
        "backends": backends,
        "config": {
            "top_k": args.top_k,
            "temperature": args.temperature,
        },
        "results": results,
        "summary": summary,
    }

    # Write reports
    os.makedirs(args.output, exist_ok=True)
    json_path = write_json_report(report, args.output)
    md_path = write_markdown_report(report, args.output)

    logger.info(f"Reports written to {args.output}/")
    logger.info(f"  JSON: {json_path}")
    logger.info(f"  Markdown: {md_path}")

    # Print summary table to stdout
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    for backend, metrics in summary.items():
        print(f"\n{backend.upper()}:")
        for key, val in metrics.items():
            if isinstance(val, float):
                print(f"  {key}: {val:.4f}")
            else:
                print(f"  {key}: {val}")

    await client.aclose()
