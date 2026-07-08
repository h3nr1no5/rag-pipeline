"""DSPy pipeline module for API documentation RAG.

Task 7.2: Implement APIDocRAG module orchestrating query analysis, retrieval,
context assembly, and generation.

Task 7.3: DSPy assertions for quality — implemented as explicit validation
steps with retry/fallback (DSPy v3 does not ship ``dspy.Suggest``).
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import TYPE_CHECKING, Any

import dspy

from src.domain.services.verification import validate_parameter_claims

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
    """Format retrieved chunks into plain text separated by blank lines."""
    parts: list[str] = []
    for node, _score in chunks:
        content = node.content.strip()
        parts.append(content)
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
        ``retrieved_chunks``, ``assertions_passed``, ``used_fallback``,
        ``retry_stage``, ``parameter_validation``.
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
        # NOTE: This method runs in a thread pool worker (called via
        # asyncio.to_thread from manager.py), so we use asyncio.run() to
        # bridge DSPy's synchronous forward() contract with async retrieval.
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
                "retry_stage": None,
                "parameter_validation": {
                    "is_valid": True,
                    "unsupported_parameter_claims": [],
                    "supported_parameter_claims": [],
                    "confidence": 1.0,
                },
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
            ranked_chunks=ranked_chunks,
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
            "retry_stage": result.get("retry_stage"),
            "parameter_validation": result.get("parameter_validation"),
        }

    # ------------------------------------------------------------------
    # Async public API
    # ------------------------------------------------------------------

    async def aforward(
        self,
        question: str,
        top_k: int = 10,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Async version of :meth:`forward`.

        Mirrors the same input validation and parameter-override logic
        but uses ``await`` instead of synchronous sub-module calls.
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
            original_temperature = (
                lm.temperature if hasattr(lm, "temperature") else None
            )
            lm.temperature = temperature

        # Apply per-call max_tokens override if provided -----------------
        original_max_tokens: int | None = None
        if max_tokens is not None and lm is not None:
            max_tokens = max(64, min(4096, max_tokens))
            original_max_tokens = (
                lm.kwargs.get("max_tokens") if hasattr(lm, "kwargs") else None
            )
            lm.kwargs["max_tokens"] = max_tokens

        try:
            return await self._aforward_impl(question, top_k)
        finally:
            # Restore original temperature
            if (
                temperature is not None
                and lm is not None
                and original_temperature is not None
            ):
                lm.temperature = original_temperature
            # Restore original max_tokens
            if (
                max_tokens is not None
                and lm is not None
                and original_max_tokens is not None
            ):
                lm.kwargs["max_tokens"] = original_max_tokens

    async def _aforward_impl(
        self,
        question: str,
        top_k: int,
    ) -> dict[str, Any]:
        """Async internal pipeline implementation.

        Unlike :meth:`_forward_impl`, this does **not** wrap the hybrid
        retriever call in ``asyncio.run()`` — it ``await``\\ s it directly.
        The synchronous ``_generate_with_assertions`` step is bridged via
        ``asyncio.to_thread``.
        """
        # 1. Use raw question directly (no QueryAnalyzer) --------------------
        search_queries = [question]

        # 2. Hybrid retrieval (native async — no asyncio.run) ---------------
        all_chunks: dict[str, tuple[ChunkNode, float]] = {}
        for query in search_queries:
            try:
                results: list[tuple[ChunkNode, float]] = (
                    await self.hybrid_retriever.retrieve(query, top_k=top_k)
                )
                for node, score in results:
                    # Keep the best score per chunk
                    if (
                        node.chunk_id not in all_chunks
                        or score > all_chunks[node.chunk_id][1]
                    ):
                        all_chunks[node.chunk_id] = (node, score)
            except (TimeoutError, ValueError):
                logger.warning(
                    "Retrieval failed for query (len=%d) — skipping", len(query)
                )

        ranked_chunks = sorted(
            all_chunks.values(), key=lambda x: x[1], reverse=True
        )

        # Limit chunks passed to generator to avoid noise and token bloat
        ranked_chunks = ranked_chunks[: self.MAX_CONTEXT_CHUNKS]

        if not ranked_chunks:
            logger.warning("No chunks retrieved — returning empty response")
            return {
                "answer": (
                    "I could not find relevant information "
                    "in the API documentation."
                ),
                "rationale": "",
                "citations": [],
                "relevant_functions": [],
                "relevant_types": [],
                "confidence": 0.0,
                "primary_chunk_id": "",
                "retrieved_chunks": [],
                "assertions_passed": False,
                "used_fallback": False,
                "retry_stage": None,
                "parameter_validation": {
                    "is_valid": True,
                    "unsupported_parameter_claims": [],
                    "supported_parameter_claims": [],
                    "confidence": 1.0,
                },
            }

        # 3. Use all chunks directly (no ContextAssembler) -------------------
        formatted_chunks = _format_chunks(ranked_chunks)
        available_functions, available_types = _collect_available_names(
            ranked_chunks
        )
        context = formatted_chunks
        primary_chunk_id = ranked_chunks[0][0].chunk_id

        # 4. Response generation (with retry) — sync, bridge via to_thread ---
        result = await asyncio.to_thread(
            functools.partial(
                self._generate_with_assertions,
                question=question,
                context=context,
                available_functions=available_functions,
                available_types=available_types,
                ranked_chunks=ranked_chunks,
            )
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
            "retry_stage": result.get("retry_stage"),
            "parameter_validation": result.get("parameter_validation"),
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
        ranked_chunks: list[tuple[ChunkNode, float]] | None = None,
    ) -> dict[str, Any]:
        """Generate response with 3-strike assertion retry.

        Tries :class:`ChainOfThought` first (Strike 1).  If assertions fail,
        falls back to a plain :class:`Predict` (Strike 2).  If that also fails
        assertions, returns a structured fallback answer (Strike 3).

        The returned dict always includes a ``retry_stage`` field indicating
        which stage produced the final answer:
        - ``"cot"`` — CoT passed assertions
        - ``"predict"`` — CoT failed, Predict passed
        - ``"fallback"`` — Both CoT and Predict failed assertions
        """
        # ------------------------------------------------------------------
        # Strike 1: ChainOfThought
        # ------------------------------------------------------------------
        try:
            response = self.response_generator(
                context=context,
                question=question,
            )
            cot_answer = response.answer.strip()
            cot_rationale = (
                getattr(response, "reasoning", "")
                or getattr(response, "rationale", "")
                or ""
            ).strip()
            cot_citations = _parse_multiline(response.citations)
            cot_functions = _parse_multiline(response.relevant_functions)
            cot_types = _parse_multiline(response.relevant_types)
            cot_confidence = float(response.confidence)
        except Exception:
            logger.exception("APIResponseGenerator (CoT) failed — trying Predict fallback")
            # CoT raised → skip straight to Strike 2
            return self._strike_2_predict(
                question, context, available_functions, available_types, ranked_chunks
            )

        # Validate assertions on CoT output
        cot_citations_valid = validate_citations(
            answer=cot_answer,
            citations=cot_citations,
            available_functions=available_functions,
            available_types=available_types,
        )
        cot_refs_valid = check_question_references(
            question=question,
            answer=cot_answer,
            available_functions=available_functions,
            available_types=available_types,
        )
        cot_assertions_passed = cot_citations_valid["valid"] and cot_refs_valid["valid"]

        if cot_assertions_passed:
            # Strike 1 succeeded
            result: dict[str, Any] = {
                "answer": cot_answer,
                "rationale": cot_rationale,
                "citations": cot_citations,
                "relevant_functions": cot_functions,
                "relevant_types": cot_types,
                "confidence": cot_confidence,
                "assertions_passed": True,
                "used_fallback": False,
                "retry_stage": "cot",
            }
            result["parameter_validation"] = self._validate_parameter_claims(
                cot_answer, ranked_chunks
            )
            return result

        # CoT failed assertions — log and proceed to Strike 2
        logger.warning(
            "DSPy assertion failed (CoT): citations=%s refs=%s",
            cot_citations_valid["message"],
            cot_refs_valid["message"],
        )
        return self._strike_2_predict(
            question, context, available_functions, available_types, ranked_chunks
        )

    def _strike_2_predict(
        self,
        question: str,
        context: str,
        available_functions: set[str],
        available_types: set[str],
        ranked_chunks: list[tuple[ChunkNode, float]] | None = None,
    ) -> dict[str, Any]:
        """Strike 2: run Predict fallback and validate assertions.

        Called when Strike 1 (CoT) fails assertions or raises an exception.
        If Predict succeeds and passes assertions → return with
        ``retry_stage="predict"``.  Otherwise → fall through to Strike 3.
        """
        try:
            response = self.fallback_generator(
                context=context,
                question=question,
            )
            predict_answer = response.answer.strip()
            predict_citations = _parse_multiline(response.citations)
            predict_functions = _parse_multiline(response.relevant_functions)
            predict_types = _parse_multiline(response.relevant_types)
            predict_confidence = float(response.confidence)
        except Exception:
            logger.exception("Fallback generator also failed — returning structured fallback")
            return self._structured_fallback(ranked_chunks)

        # Validate assertions on Predict output
        predict_citations_valid = validate_citations(
            answer=predict_answer,
            citations=predict_citations,
            available_functions=available_functions,
            available_types=available_types,
        )
        predict_refs_valid = check_question_references(
            question=question,
            answer=predict_answer,
            available_functions=available_functions,
            available_types=available_types,
        )
        predict_assertions_passed = (
            predict_citations_valid["valid"] and predict_refs_valid["valid"]
        )

        if predict_assertions_passed:
            # Strike 2 succeeded
            result: dict[str, Any] = {
                "answer": predict_answer,
                "rationale": "",
                "citations": predict_citations,
                "relevant_functions": predict_functions,
                "relevant_types": predict_types,
                "confidence": predict_confidence,
                "assertions_passed": True,
                "used_fallback": True,
                "retry_stage": "predict",
            }
            result["parameter_validation"] = self._validate_parameter_claims(
                predict_answer, ranked_chunks
            )
            return result

        # Both CoT and Predict failed assertions — Strike 3
        logger.warning(
            "DSPy assertion failed (Predict): citations=%s refs=%s",
            predict_citations_valid["message"],
            predict_refs_valid["message"],
        )
        return self._structured_fallback(ranked_chunks)

    def _structured_fallback(
        self,
        ranked_chunks: list[tuple[ChunkNode, float]] | None = None,
    ) -> dict[str, Any]:
        """Strike 3: return a safe structured fallback answer.

        Called when both CoT and Predict fail assertions or raise exceptions.
        The answer directs users to review the source documentation directly.
        """
        answer = (
            "I found relevant documentation but couldn't generate a verified response. "
            "Please review the source documentation directly."
        )
        result: dict[str, Any] = {
            "answer": answer,
            "rationale": "",
            "citations": [],
            "relevant_functions": [],
            "relevant_types": [],
            "confidence": 0.0,
            "assertions_passed": False,
            "used_fallback": True,
            "retry_stage": "fallback",
        }
        result["parameter_validation"] = self._validate_parameter_claims(
            answer, ranked_chunks
        )
        return result

    def _validate_parameter_claims(
        self,
        answer: str,
        ranked_chunks: list[tuple[ChunkNode, float]] | None,
    ) -> dict:
        """Validate parameter claims in *answer* against *ranked_chunks* metadata.

        Converts ``ChunkNode`` objects to plain dicts expected by
        ``validate_parameter_claims`` and delegates to the verification module.
        """
        try:
            if not ranked_chunks:
                return validate_parameter_claims(answer, [])

            context_dicts: list[dict] = []
            for node, _score in ranked_chunks:
                context_dicts.append({"metadata": node.metadata or {}})

            return validate_parameter_claims(answer, context_dicts)
        except Exception:
            logger.exception("Parameter claim validation failed in DSPy module")
            return {
                "is_valid": True,
                "unsupported_parameter_claims": [],
                "supported_parameter_claims": [],
                "confidence": 1.0,
            }
