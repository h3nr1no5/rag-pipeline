"""Evaluation metrics for the API documentation RAG pipeline.

Task 7.4: Evaluation metrics compatible with ``dspy.Evaluate``.

Each metric is a callable ``(example, prediction, trace=None) -> float``
as required by ``dspy.Evaluate``.  *example* is a ``dspy.Example`` with
at minimum attributes ``question`` and ``gold_functions`` / ``gold_types``.
*prediction* is a dict-like object (the output of ``APIDocRAG.forward()``).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[([^\]]+)\]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_list(value: Any) -> list[str]:
    """Normalise a value to a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [v.strip() for v in value.split("\n") if v.strip()]
    return []


def _cited_names(answer: str) -> set[str]:
    """Extract all ``[Name]`` tokens from the answer text."""
    return set(_CITATION_RE.findall(answer))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def retrieval_recall(
    example: Any,
    prediction: Any,
    trace: Any = None,
) -> float:
    """Fraction of gold-standard functions/types present in top-5 retrieved chunks.

    Parameters
    ----------
    example:
        Must have ``gold_functions`` and/or ``gold_types`` attributes (each
        a list of strings).
    prediction:
        Should be a dict with key ``retrieved_chunks`` (list of
        ``(chunk_id, score)`` tuples from :class:`APIDocRAG`).

    Returns
    -------
    ``1.0`` if all gold items appear in retrieved chunk IDs or metadata,
    ``0.0`` if none, linear fraction otherwise.
    """
    gold: set[str] = set()
    gold.update(_ensure_list(getattr(example, "gold_functions", [])))
    gold.update(_ensure_list(getattr(example, "gold_types", [])))

    if not gold:
        return 1.0  # nothing to recall

    # Retrieve top-5 chunk IDs
    retrieved_chunks = getattr(prediction, "retrieved_chunks", None)
    if retrieved_chunks is None and isinstance(prediction, dict):
        retrieved_chunks = prediction.get("retrieved_chunks", [])

    chunk_ids: set[str] = set()
    if retrieved_chunks:
        for cid, _score in retrieved_chunks[:5]:
            chunk_ids.add(str(cid))

    if not chunk_ids:
        return 0.0

    # Count gold names that appear in any chunk ID (simple heuristic)
    # This is intentionally approximate — a proper implementation would
    # check chunk metadata as well.
    found = sum(1 for name in gold if name.lower() in " ".join(chunk_ids).lower())

    return found / len(gold)


def citation_accuracy(
    example: Any,
    prediction: Any,
    trace: Any = None,
) -> float:
    """Fraction of citations that reference actual functions/types.

    Uses the prediction's ``citations`` list and the example's
    ``gold_functions`` + ``gold_types`` as the authoritative set.  Inline
    ``[Name]`` tokens from ``answer`` are also checked.

    Parameters
    ----------
    example:
        Must have ``gold_functions`` and ``gold_types`` attributes.
    prediction:
        Dict with keys ``citations``, ``answer``.
    """
    # Build known set
    known: set[str] = set()
    known.update(_ensure_list(getattr(example, "gold_functions", [])))
    known.update(_ensure_list(getattr(example, "gold_types", [])))

    if not known:
        return 1.0  # can't be wrong if there's no gold standard

    # Collect all cited names
    answer = getattr(prediction, "answer", None)
    if answer is None and isinstance(prediction, dict):
        answer = prediction.get("answer", "")

    citations_raw = getattr(prediction, "citations", None)
    if citations_raw is None and isinstance(prediction, dict):
        citations_raw = prediction.get("citations", [])

    cited: set[str] = _cited_names(answer or "")
    cited.update(_ensure_list(citations_raw))

    if not cited:
        return 0.0  # no citations at all

    correct = sum(1 for name in cited if name in known)
    return correct / len(cited)


def hallucination_rate(
    example: Any,
    prediction: Any,
    trace: Any = None,
) -> float:
    """Fraction of statements in answer not supported by retrieved context.

    This is a **simplified** heuristic: counts citations that reference names
    **not** in the gold-standard set, divided by total citations.

    .. note::

        A ``0.0`` means no hallucinations (best).  A ``1.0`` means every
        citation is fictitious.  Returns ``0.0`` when there are no citations
        (vacuously truthful).

    Parameters
    ----------
    example:
        Must have ``gold_functions`` and ``gold_types`` attributes.
    prediction:
        Dict with keys ``citations``, ``answer``.
    """
    known: set[str] = set()
    known.update(_ensure_list(getattr(example, "gold_functions", [])))
    known.update(_ensure_list(getattr(example, "gold_types", [])))

    answer = getattr(prediction, "answer", None)
    if answer is None and isinstance(prediction, dict):
        answer = prediction.get("answer", "")

    citations_raw = getattr(prediction, "citations", None)
    if citations_raw is None and isinstance(prediction, dict):
        citations_raw = prediction.get("citations", [])

    cited: set[str] = _cited_names(answer or "")
    cited.update(_ensure_list(citations_raw))

    if not cited:
        return 0.0  # no citations → no hallucinations (vacuously true)

    hallucinated = sum(1 for name in cited if name not in known)
    return hallucinated / len(cited)


def composite_score(
    example: Any,
    prediction: Any,
    trace: Any = None,
) -> float:
    """Weighted combination of retrieval recall, citation accuracy, and inverse hallucination rate.

    Weights (configurable via ``composite_score.weights``):

    - retrieval recall: 0.3
    - citation accuracy: 0.4
    - (1 - hallucination_rate): 0.3

    Parameters
    ----------
    example:
        Passed through to sub-metrics.
    prediction:
        Passed through to sub-metrics.
    """
    recall = retrieval_recall(example, prediction, trace)
    citation_acc = citation_accuracy(example, prediction, trace)
    hallu = hallucination_rate(example, prediction, trace)
    truthfulness = 1.0 - hallu

    # Weights
    w_recall = 0.3
    w_citation = 0.4
    w_truth = 0.3

    score = (
        w_recall * recall + w_citation * citation_acc + w_truth * truthfulness
    )
    return score
