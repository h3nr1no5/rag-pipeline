"""DSPy pipeline module for API documentation RAG.

Exposes the public API for the generation pipeline:

- Signatures: :class:`QueryAnalyzer`, :class:`ContextAssembler`,
  :class:`APIResponseGenerator`
- Module: :class:`APIDocRAG`
- Assertions: :func:`validate_citations`, :func:`check_question_references`
- Metrics: :func:`retrieval_recall`, :func:`citation_accuracy`,
  :func:`hallucination_rate`, :func:`composite_score`
"""

from .assertions import check_question_references, validate_citations
from .metrics import (
    citation_accuracy,
    composite_score,
    hallucination_rate,
    retrieval_recall,
)
from .module import APIDocRAG
from .signatures import (
    APIResponseGenerator,
    ContextAssembler,
    QueryAnalyzer,
)

__all__ = [
    "APIDocRAG",
    "APIResponseGenerator",
    "ContextAssembler",
    "QueryAnalyzer",
    "check_question_references",
    "citation_accuracy",
    "composite_score",
    "hallucination_rate",
    "retrieval_recall",
    "validate_citations",
]
