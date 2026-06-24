"""DSPy pipeline module for API documentation RAG.

Task 7.2: Implement APIDocRAG module orchestrating query analysis, retrieval,
context assembly, and generation.

Task 7.3: DSPy assertions for quality — implemented as explicit validation
steps with retry/fallback (DSPy v3 does not ship ``dspy.Suggest``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import dspy

from .assertions import check_question_references, validate_citations
from .signatures import (
    APIResponseGenerator,
    ContextAssembler,
    QueryAnalyzer,
)

if TYPE_CHECKING:
    from src.domain.rag.api_docs.chunking.graph import ChunkNode
    from src.domain.rag.api_docs.retrieval.hybrid_retriever import (
        HybridRetriever,
    )

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_multiline(text: str) -> list[str]:
    """Split a newline-separated string into a non-empty stripped list."""
    return [line.strip() for line in text.split("\n") if line.strip()]


def _format_chunks(chunks: list[tuple[ChunkNode, float]]) -> str:
    """Format retrieved chunks into the text format ContextAssembler expects.

    Each chunk is prefixed with ``[chunk_id]``, followed by its content,
    separated by a blank line.
    """
    parts: list[str] = []
    for node, _score in chunks:
        # Strip any existing bracketed IDs from the content to avoid confusion
        content = node.content.strip()
        parts.append(f"[{node.chunk_id}]\n{content}")
    return "\n\n".join(parts)


def _collect_available_names(
    chunks: list[tuple[ChunkNode, float]],
) -> tuple[set[str], set[str]]:
    """Collect all function and type names from the retrieved chunks' metadata."""
    functions: set[str] = set()
    types: set[str] = set()
    for node, _score in chunks:
        meta = node.metadata or {}
        if func_name := meta.get("function_name"):
            functions.add(func_name)
        if iface_name := meta.get("interface_name"):
            types.add(iface_name)
        # Also collect from content: look for ``Name`` patterns
        # (defensive — metadata is the primary source)
    return functions, types


# ---------------------------------------------------------------------------
# APIDocRAG Module
# ---------------------------------------------------------------------------


class APIDocRAG(dspy.Module):
    """DSPy module that orchestrates the full API documentation RAG pipeline.

    Pipeline steps
    --------------
    1. **Query analysis** — extract search queries, target types, and intent
       from the user's question via :class:`QueryAnalyzer`.
    2. **Hybrid retrieval** — for each search query, call the
       :class:`HybridRetriever` and collect unique chunks.
    3. **Context assembly** — format and select chunks via
       :class:`ContextAssembler`.
    4. **Response generation** — produce a cited answer via
       :class:`APIResponseGenerator`.
    5. **Quality assertions** — validate citations and references; retry with
       a simpler (non-chain-of-thought) strategy on failure.

    Parameters
    ----------
    hybrid_retriever:
        The retrieval backend (BM25 + embedding + RRF).
    """

    def __init__(self, hybrid_retriever: HybridRetriever) -> None:
        super().__init__()

        self.hybrid_retriever = hybrid_retriever

        # ChainOfThought predictors (better quality for analysis / generation)
        self.query_analyzer = dspy.ChainOfThought(QueryAnalyzer)
        self.context_assembler = dspy.ChainOfThought(ContextAssembler)
        self.response_generator = dspy.ChainOfThought(APIResponseGenerator)

        # Fallback: plain Predict (used when assertions fail)
        self.fallback_generator = dspy.Predict(APIResponseGenerator)

        logger.info("APIDocRAG module initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def forward(
        self,
        question: str,
        top_k: int = 10,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Run the full pipeline for a single *question*.

        Parameters
        ----------
        question:
            The user's question about the API documentation.
        top_k:
            Number of chunks to retrieve per search query.

        Returns
        -------
        dict with keys ``answer``, ``citations``, ``relevant_functions``,
        ``relevant_types``, ``confidence``, ``primary_chunk_id``,
        ``retrieved_chunks``, ``assertions_passed``, ``used_fallback``.
        """
        # Apply per-call temperature override if provided -----------------
        lm = dspy.settings.lm
        original_temperature: float | None = None
        if temperature is not None and lm is not None:
            original_temperature = lm.temperature if hasattr(lm, "temperature") else None
            lm.temperature = temperature

        try:
            return self._forward_impl(question, top_k)
        finally:
            # Restore original temperature
            if temperature is not None and lm is not None and original_temperature is not None:
                lm.temperature = original_temperature

    def _forward_impl(
        self,
        question: str,
        top_k: int,
    ) -> dict[str, Any]:
        """Internal pipeline implementation (separated for temperature wrapping)."""
        # 1. Query analysis ------------------------------------------------
        try:
            analysis = self.query_analyzer(question=question)
            search_queries = _parse_multiline(analysis.search_queries)
            target_types = _parse_multiline(analysis.target_types)
            intent = analysis.intent.strip()
            logger.info(
                "QueryAnalyzer: intent=%s queries=%s types=%s",
                intent, search_queries[:3], target_types[:3],
            )
        except Exception:
            logger.exception("QueryAnalyzer failed — falling back to raw question")
            search_queries = [question]
            target_types = []
            intent = "how_to"

        # 2. Hybrid retrieval ----------------------------------------------
        all_chunks: dict[str, tuple[ChunkNode, float]] = {}
        for query in search_queries:
            try:
                results: list[tuple[ChunkNode, float]] = asyncio.run(
                    self.hybrid_retriever.retrieve(query, top_k=top_k)
                )
                for node, score in results:
                    # Keep the best score per chunk
                    if node.chunk_id not in all_chunks or score > all_chunks[node.chunk_id][1]:
                        all_chunks[node.chunk_id] = (node, score)
            except Exception:
                logger.warning("Retrieval failed for query %r — skipping", query)

        ranked_chunks = sorted(all_chunks.values(), key=lambda x: x[1], reverse=True)

        if not ranked_chunks:
            logger.warning("No chunks retrieved — returning empty response")
            return {
                "answer": "I could not find relevant information in the API documentation.",
                "citations": [],
                "relevant_functions": [],
                "relevant_types": [],
                "confidence": 0.0,
                "primary_chunk_id": "",
                "retrieved_chunks": [],
                "assertions_passed": False,
                "used_fallback": False,
            }

        # 3. Context assembly ----------------------------------------------
        formatted_chunks = _format_chunks(ranked_chunks)
        available_functions, available_types = _collect_available_names(ranked_chunks)

        try:
            assembled = self.context_assembler(
                question=question,
                chunks=formatted_chunks,
            )
            context = assembled.assembled_context.strip()
            primary_chunk_id = assembled.primary_chunk_id.strip()
        except Exception:
            logger.exception("ContextAssembler failed — using all chunks")
            context = formatted_chunks
            primary_chunk_id = ranked_chunks[0][0].chunk_id if ranked_chunks else ""

        # 4. Response generation (with retry) ------------------------------
        result = self._generate_with_assertions(
            question=question,
            context=context,
            available_functions=available_functions,
            available_types=available_types,
        )

        # 5. Build final response dict -------------------------------------
        return {
            "answer": result["answer"],
            "citations": result["citations"],
            "relevant_functions": result["relevant_functions"],
            "relevant_types": result["relevant_types"],
            "confidence": result["confidence"],
            "primary_chunk_id": primary_chunk_id,
            "retrieved_chunks": [(n.chunk_id, s) for n, s in ranked_chunks],
            "assertions_passed": result["assertions_passed"],
            "used_fallback": result["used_fallback"],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_with_assertions(
        self,
        question: str,
        context: str,
        available_functions: set[str],
        available_types: set[str],
    ) -> dict[str, Any]:
        """Generate response, validate, and retry with fallback if needed.

        Tries :class:`ChainOfThought` first.  If assertions fail, falls back
        to a plain :class:`Predict` (no chain-of-thought) and tries once more.
        """
        # --- First attempt: ChainOfThought ---
        try:
            response = self.response_generator(
                context=context,
                question=question,
            )
            answer = response.answer.strip()
            citations = _parse_multiline(response.citations)
            relevant_functions = _parse_multiline(response.relevant_functions)
            relevant_types = _parse_multiline(response.relevant_types)
            confidence = float(response.confidence)
        except Exception:
            logger.exception("APIResponseGenerator (CoT) failed — falling back")
            # Treat as failed assertions -> fallback
            return self._generate_fallback(
                question, context, available_functions, available_types
            )

        # Validate assertions
        citations_valid = validate_citations(
            answer=answer,
            citations=citations,
            available_functions=available_functions,
            available_types=available_types,
        )
        refs_valid = check_question_references(
            question=question,
            answer=answer,
            available_functions=available_functions,
            available_types=available_types,
        )

        assertions_passed = citations_valid["valid"] and refs_valid["valid"]
        if not assertions_passed:
            logger.warning(
                "DSPy assertion failed: citations=%s refs=%s",
                citations_valid["message"],
                refs_valid["message"],
            )

        # Return the CoT output regardless — assertions are advisory only
        return {
            "answer": answer,
            "citations": citations,
            "relevant_functions": relevant_functions,
            "relevant_types": relevant_types,
            "confidence": confidence,
            "assertions_passed": assertions_passed,
            "used_fallback": False,
        }

    def _generate_fallback(
        self,
        question: str,
        context: str,
        available_functions: set[str],
        available_types: set[str],
    ) -> dict[str, Any]:
        """Generate response with plain Predict (no chain-of-thought)."""
        try:
            response = self.fallback_generator(
                context=context,
                question=question,
            )
            answer = response.answer.strip()
            citations = _parse_multiline(response.citations)
            relevant_functions = _parse_multiline(response.relevant_functions)
            relevant_types = _parse_multiline(response.relevant_types)
            confidence = float(response.confidence)
        except Exception:
            logger.exception("Fallback generator also failed")
            return {
                "answer": "I encountered an error generating the answer.",
                "citations": [],
                "relevant_functions": [],
                "relevant_types": [],
                "confidence": 0.0,
                "assertions_passed": False,
                "used_fallback": True,
            }

        return {
            "answer": answer,
            "citations": citations,
            "relevant_functions": relevant_functions,
            "relevant_types": relevant_types,
            "confidence": confidence,
            "assertions_passed": False,
            "used_fallback": True,
        }
