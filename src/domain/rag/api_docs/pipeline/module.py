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
    1. **Query analysis** — Raw question used directly for retrieval.
    2. **Hybrid retrieval** — for each search query, call the
       :class:`HybridRetriever` and collect unique chunks.
    3. **Context assembly** — All chunks passed directly to generator.
    4. **Response generation** — produce a cited answer via
       :class:`APIResponseGenerator`.
    5. **Quality assertions** — validate citations and references; retry with
       a simpler (non-chain-of-thought) strategy on failure.

    Parameters
    ----------
    hybrid_retriever:
        The retrieval backend (BM25 + embedding + RRF).
    """

    # Max chunks to pass to the response generator (avoids noise/token bloat)
    MAX_CONTEXT_CHUNKS: int = 10

    def __init__(self, hybrid_retriever: HybridRetriever) -> None:
        super().__init__()

        self.hybrid_retriever = hybrid_retriever

        # ChainOfThought predictors (better quality for generation)
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
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Run the full pipeline for a single *question*.

        Parameters
        ----------
        question:
            The user's question about the API documentation.
        top_k:
            Number of chunks to retrieve per search query.
        temperature:
            Override the generation temperature. ``None`` uses the default.
        max_tokens:
            Override the generation max tokens. ``None`` uses the default.

        Returns
        -------
        dict with keys ``answer``, ``citations``, ``relevant_functions``,
        ``relevant_types``, ``confidence``, ``primary_chunk_id``,
        ``retrieved_chunks``, ``assertions_passed``, ``used_fallback``.
        """
        # --- Input validation ------------------------------------------------
        if not question or not question.strip():
            raise ValueError("question cannot be empty")
        if len(question) > 2000:
            raise ValueError("question too long (max 2000 characters)")

        # Apply per-call temperature override if provided -----------------
        lm = dspy.settings.lm
        original_temperature: float | None = None
        if temperature is not None and lm is not None:
            temperature = max(0.0, min(1.0, temperature))
            original_temperature = lm.temperature if hasattr(lm, "temperature") else None
            lm.temperature = temperature

        # Apply per-call max_tokens override if provided -----------------
        original_max_tokens: int | None = None
        if max_tokens is not None and lm is not None:
            max_tokens = max(64, min(4096, max_tokens))
            original_max_tokens = lm.kwargs.get("max_tokens") if hasattr(lm, "kwargs") else None
            lm.kwargs["max_tokens"] = max_tokens

        try:
            return self._forward_impl(question, top_k)
        finally:
            # Restore original temperature
            if temperature is not None and lm is not None and original_temperature is not None:
                lm.temperature = original_temperature
            # Restore original max_tokens
            if max_tokens is not None and lm is not None and original_max_tokens is not None:
                lm.kwargs["max_tokens"] = original_max_tokens

    def _forward_impl(
        self,
        question: str,
        top_k: int,
    ) -> dict[str, Any]:
        """Internal pipeline implementation (separated for temperature wrapping)."""
        # 1. Use raw question directly (no QueryAnalyzer) --------------------
        search_queries = [question]

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
            except (TimeoutError, ValueError):
                logger.warning("Retrieval failed for query (len=%d) — skipping", len(query))

        ranked_chunks = sorted(all_chunks.values(), key=lambda x: x[1], reverse=True)

        # Limit chunks passed to generator to avoid noise and token bloat
        ranked_chunks = ranked_chunks[:self.MAX_CONTEXT_CHUNKS]

        if not ranked_chunks:
            logger.warning("No chunks retrieved — returning empty response")
            return {
                "answer": "I could not find relevant information in the API documentation.",
                "rationale": "",
                "citations": [],
                "relevant_functions": [],
                "relevant_types": [],
                "confidence": 0.0,
                "primary_chunk_id": "",
                "retrieved_chunks": [],
                "assertions_passed": False,
                "used_fallback": False,
            }

        # 3. Use all chunks directly (no ContextAssembler) -------------------
        formatted_chunks = _format_chunks(ranked_chunks)
        available_functions, available_types = _collect_available_names(ranked_chunks)
        context = formatted_chunks
        primary_chunk_id = ranked_chunks[0][0].chunk_id

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
            "rationale": result["rationale"],
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
            rationale = (
                getattr(response, "reasoning", "")
                or getattr(response, "rationale", "")
                or ""
            ).strip()
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
            "rationale": rationale,
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
                "rationale": "",
                "citations": [],
                "relevant_functions": [],
                "relevant_types": [],
                "confidence": 0.0,
                "assertions_passed": False,
                "used_fallback": True,
            }

        return {
            "answer": answer,
            "rationale": "",
            "citations": citations,
            "relevant_functions": relevant_functions,
            "relevant_types": relevant_types,
            "confidence": confidence,
            "assertions_passed": False,
            "used_fallback": True,
        }
