"""Retrieval and answer quality metrics for RAG evaluation."""
import logging

from src.domain.services.verification import ResponseVerifier

logger = logging.getLogger(__name__)


def precision_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    """Precision@k = |relevant ∩ retrieved[:k]| / k

    Args:
        relevant: Set of relevant chunk IDs
        retrieved: List of retrieved chunk IDs (ordered by rank)
        k: Number of top results to consider

    Returns:
        Precision@k as a float between 0.0 and 1.0
    """
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    return len(relevant.intersection(top_k)) / k


def recall_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    """Recall@k = |relevant ∩ retrieved[:k]| / |relevant|

    Args:
        relevant: Set of relevant chunk IDs
        retrieved: List of retrieved chunk IDs (ordered by rank)
        k: Number of top results to consider

    Returns:
        Recall@k as a float between 0.0 and 1.0 (0.0 if no relevant chunks)
    """
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    return len(relevant.intersection(top_k)) / len(relevant)


def mrr(relevant: set[str], retrieved: list[str]) -> float:
    """Mean Reciprocal Rank: 1 / rank_of_first_relevant_chunk

    Args:
        relevant: Set of relevant chunk IDs
        retrieved: List of retrieved chunk IDs (ordered by rank)

    Returns:
        MRR as a float between 0.0 and 1.0 (0.0 if no relevant chunk found)
    """
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def keyword_recall(answer: str, expected_keywords: list[str]) -> float:
    """Keyword recall: |{keywords_in_answer}| / |{expected_keywords}|

    Case-insensitive matching. Each keyword is checked if it appears
    anywhere in the answer text.

    Args:
        answer: The generated answer text
        expected_keywords: List of keywords expected in the answer

    Returns:
        Keyword recall as a float between 0.0 and 1.0
    """
    if not expected_keywords:
        return 1.0
    if not answer:
        return 0.0

    answer_lower = answer.lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return found / len(expected_keywords)


async def faithfulness(
    answer: str,
    source_texts: list[str],
    verifier: ResponseVerifier | None = None,
) -> float:
    """Compute faithfulness score using ResponseVerifier cross-encoder.

    Args:
        answer: The generated answer text
        source_texts: List of source chunk content strings
        verifier: Optional ResponseVerifier instance (created if not provided)

    Returns:
        Faithfulness confidence between 0.0 and 1.0, or 0.0 if verification
        fails/disabled. Logs a warning on failure.
    """
    if not answer or not source_texts:
        return 0.0

    # Build simple source objects with .content attr for ResponseVerifier
    class _Source:
        def __init__(self, content: str):
            self.content = content

    sources = [_Source(t) for t in source_texts]

    try:
        if verifier is None:
            verifier = ResponseVerifier()
        result = await verifier.verify(answer, sources)
        return result.confidence
    except Exception as e:
        logger.warning(f"Faithfulness computation failed: {e}")
        return 0.0
