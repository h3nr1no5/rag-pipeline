"""Reciprocal Rank Fusion (RRF) for merging ranked retrieval results.

Task 5.3: RrfFusion implementation.

Combines multiple ranked result lists (e.g. BM25 + embedding) into a single
ranked list using the RRF formula:

    RRF score(d) = Σ 1 / (k + rank(d, list))

where ``k`` is a smoothing constant (default 60 per spec) and ``rank`` is
1-based position in each result list.
"""

from __future__ import annotations


class RrfFusion:
    """Reciprocal Rank Fusion combiner.

    Attributes:
        k: The RRF smoothing constant (default 60).
    """

    def __init__(self, k: int = 60) -> None:
        self.k = k

    def fuse(
        self, results: list[list[tuple[str, float]]]
    ) -> list[tuple[str, float]]:
        """Fuse multiple ranked result lists into one.

        Args:
            results: A list of ranked lists.  Each inner list contains
                     ``(chunk_id, score)`` tuples in descending score order.
                     The original scores are **not** used by RRF — only
                     the rank position matters.

        Returns:
            A single ranked list of ``(chunk_id, rrf_score)`` tuples sorted
            by descending RRF score.  Each chunk_id appears at most once.
            Returns an empty list if *results* is empty or all sub-lists are
            empty.
        """
        rrf_scores: dict[str, float] = {}

        for ranked_list in results:
            for rank, (doc_id, _) in enumerate(ranked_list):
                # rank is 0-based → RRF uses 1-based position
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (
                    self.k + rank + 1
                )

        # Sort descending by RRF score
        fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return fused
