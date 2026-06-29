"""Quality assertions for the DSPy API documentation pipeline.

Task 7.3: DSPy assertions for quality (citation presence, function reference
validation).

DSPy v3 does **not** ship built-in ``dspy.Suggest`` / ``dspy.Assert`` helpers
(the v2 assertion framework was removed).  Instead, we provide pure-Python
validation functions that the pipeline module calls explicitly.  The module
retries with a simpler (non-chain-of-thought) strategy when assertions fail.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet

logger = logging.getLogger(__name__)

# Regex to extract ``[Name]`` citations from generated answer text
_CITATION_RE = re.compile(r"\[([^\]]+)\]")


def extract_cited_names(answer: str) -> list[str]:
    """Return all ``[Name]`` citation tokens found in *answer*."""
    return _CITATION_RE.findall(answer)


def validate_citations(
    answer: str,
    citations: list[str],
    available_functions: AbstractSet[str],
    available_types: AbstractSet[str],
) -> dict:
    """Validate that citations reference actual functions/types.

    Parameters
    ----------
    answer:
        The generated answer text (used for inline ``[Name]`` extraction).
    citations:
        Explicit citation list from the generator output.
    available_functions:
        Set of function names that exist in the chunk graph.
    available_types:
        Set of type / interface names that exist in the chunk graph.

    Returns
    -------
    dict with keys:
        - ``valid``: ``True`` if all checks pass.
        - ``missing_inline_citations``: ``True`` if no ``[Name]`` tokens found.
        - ``unknown_citations``: list of cited names not found in either set.
        - ``message``: human-readable summary.
    """
    known = available_functions | available_types

    # 1. Check for at least one inline citation
    inline = extract_cited_names(answer)
    has_inline = len(inline) > 0
    all_cited = set(inline) | set(citations)

    # 2. Check that every citation is a known function/type
    unknown = [name for name in all_cited if name not in known]

    valid = has_inline and len(unknown) == 0

    parts: list[str] = []
    if not has_inline:
        parts.append("answer contains no inline [Name] citations")
    if unknown:
        parts.append(f"unknown citations: {unknown}")

    return {
        "valid": valid,
        "missing_inline_citations": not has_inline,
        "unknown_citations": unknown,
        "message": "; ".join(parts) if parts else "all citations valid",
    }


def check_question_references(
    question: str,
    answer: str,
    available_functions: AbstractSet[str],
    available_types: AbstractSet[str],
) -> dict:
    """Check that if *question* mentions a specific function it is referenced.

    Parameters
    ----------
    question:
        The user's original question.
    answer:
        The generated answer.
    available_functions:
        Known function names.
    available_types:
        Known type names.

    Returns
    -------
    dict with keys ``mentioned_in_question``, ``referenced_in_answer``,
    ``valid``, ``message``.
    """
    # Find any known function/type name that appears literally in the question
    known = available_functions | available_types
    mentioned = {name for name in known if name.lower() in question.lower()}

    answer_lower = answer.lower()
    referenced = {name for name in mentioned if name.lower() in answer_lower}

    valid = not mentioned or mentioned == referenced
    missing = mentioned - referenced

    return {
        "mentioned_in_question": sorted(mentioned),
        "referenced_in_answer": sorted(referenced),
        "valid": valid,
        "message": (
            f"missing references: {missing}" if missing else "all question references satisfied"
        ),
    }
