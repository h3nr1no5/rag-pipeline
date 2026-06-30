"""DSPy signatures for the API documentation RAG pipeline.

Task 7.1: Define DSPy signatures: QueryAnalyzer, ContextAssembler, APIResponseGenerator.

Each signature uses ``dspy.Signature`` with ``dspy.InputField`` and ``dspy.OutputField``.

Note on list-like output fields:
  DSPy v3 can technically annotate fields with ``list[str]``, but local MLX models
  produce unstructured text that rarely parses as valid JSON lists.  All multi-valued
  output fields are therefore declared as ``str`` and documented with a separator
  convention (newline or comma).  Consumers **MUST** split values themselves.
"""

from __future__ import annotations

import dspy


class QueryAnalyzer(dspy.Signature):
    """Analyse a user's API documentation question and produce search queries.

    The analyser extracts the user's search intent, generates one or more
    concrete search queries (including both semantic phrases and exact
    API name forms), and lists any COM interface or type names that appear
    in the question.
    """

    question: str = dspy.InputField(
        desc="The user's question about the API documentation"
    )

    # -- Outputs (all str, see module note above) --------------------------

    search_queries: str = dspy.OutputField(
        desc=(
            "List of search queries for retrieval, one per line. "
            "Include both semantic reformulations and exact API/function "
            "name forms (e.g. ``CreateNode``)."
        )
    )
    target_types: str = dspy.OutputField(
        desc=(
            "COM interface or type names mentioned in the question, "
            "one per line.  Empty if none."
        )
    )
    intent: str = dspy.OutputField(
        desc=(
            "Search intent classification.  One of: ``how_to``, "
            "``reference``, or ``troubleshooting``."
        )
    )


class ContextAssembler(dspy.Signature):
    """Select and order retrieved documentation chunks into a coherent context.

    Given the user's question and a list of chunk texts (ordered by
    descending relevance), this signature picks the most relevant chunks,
    removes redundancies, and arranges them in a logical order for the
    downstream generator.
    """

    question: str = dspy.InputField(
        desc="The user's question"
    )
    chunks: str = dspy.InputField(
        desc=(
            "Retrieved chunk text contents, separated by a blank line. "
            "Chunks are ordered by descending relevance."
        )
    )

    assembled_context: str = dspy.OutputField(
        desc=(
            "Assembled and ordered context for generation.  Only include "
            "chunks that are relevant to answering the question."
        )
    )
    primary_chunk_id: str = dspy.OutputField(
        desc="The most relevant chunk ID for the question"
    )


class APIResponseGenerator(dspy.Signature):
    """Generate an answer from API documentation context with citations.

    Produces a natural-language answer that references specific functions
    and types using inline citations in ``[FunctionName]`` format.  The
    answer must be grounded in the provided context only.
    """

    context: str = dspy.InputField(
        desc="Assembled context from API documentation"
    )
    question: str = dspy.InputField(
        desc="The user's question"
    )

    answer: str = dspy.OutputField(
        desc=(
            "A comprehensive, step-by-step answer that reasons through the API documentation. "
            "Think step by step: first understand the question, then search the context for "
            "relevant API details, and finally synthesize a complete answer."
        )
    )
    citations: str = dspy.OutputField(
        desc=(
            "List of function, method, property, record, enum or type names cited in the answer, "
            "one per line."
        )
    )
    relevant_functions: str = dspy.OutputField(
        desc=(
            "Function, method, property, record, enum or type names relevant to the question (found in context), "  # noqa: E501
            "one per line."
        )
    )
    relevant_types: str = dspy.OutputField(
        desc=(
            "Interface names relevant to the question (found in "
            "context), one per line."
        )
    )
    confidence: float = dspy.OutputField(
        desc="Confidence score 0.0-1.0 indicating how well the answer is "
        "supported by the context"
    )
