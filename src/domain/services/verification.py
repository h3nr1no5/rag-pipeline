"""Post-generation response verification for RAG pipelines.

Verifies each sentence in the generated response against source chunks
using embedding cosine similarity. Unsupported claims can be removed or flagged.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field

from ...core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class VerifiedResponse:
    """Result from response verification."""
    verified_text: str
    """The response after verification (unsupported claims removed or original)."""
    citations: list[dict] = field(default_factory=list)
    """Per-sentence citation mapping with source indices."""
    unsupported: list[str] = field(default_factory=list)
    """Sentences that were flagged or removed."""
    confidence: float = 0.0
    """Overall confidence score between 0.0 and 1.0."""


class ResponseVerifier:
    """Verifies each claim in a generated response against source chunks.

    Uses cross-encoder re-ranker for sentence-level verification (more accurate
    than bi-encoder cosine similarity). Each sentence is scored against each
    source chunk using the BGE cross-encoder loaded as a singleton.
    """

    def __init__(self):
        self._reranker = None

    async def _get_reranker(self):
        """Get or create the cross-encoder reranker singleton."""
        if self._reranker is None:
            from .retrieval_langchain import CrossEncoderReRanker
            self._reranker = CrossEncoderReRanker()
        return self._reranker

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences on . ! ? followed by space or newline."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _parse_citations(self, text: str) -> dict:
        """Parse all [Source N] citations from text.

        Returns:
            dict mapping sentence index -> list of source indices
        """
        sentences = self._split_sentences(text)
        citation_map = {}

        for i, sentence in enumerate(sentences):
            citations = re.findall(r'\[Source\s+(\d+)\]', sentence)
            citation_map[i] = [int(c) for c in citations]

        return citation_map

    def _validate_citation_indices(self, citations: dict, num_sources: int) -> dict:
        """Validate citation indices and return mapping of invalid -> replacement.

        Returns:
            dict: {invalid_source_index: valid_replacement_index}
        """
        fixes = {}
        for sentence_idx, source_indices in citations.items():
            for src_idx in source_indices:
                if src_idx < 1 or src_idx > num_sources:
                    fixes[src_idx] = 1  # Default to first source if invalid
        return fixes

    async def _score_with_cross_encoder(
        self, sentence: str, source_texts: list[str]
    ) -> list[float]:
        """Score a sentence against each source text using cross-encoder."""
        reranker = await self._get_reranker()
        pairs = [(sentence, src) for src in source_texts]
        model = await reranker._ensure_model()
        scores = await asyncio.to_thread(model.predict, pairs)
        return [float(s) for s in scores]

    async def _score_all_cross_encoder(
        self, all_pairs: list[tuple[str, str]], num_sources: int
    ) -> list[list[float]]:
        """Score all (sentence, source) pairs in a single model.predict() call.

        Args:
            all_pairs: List of (sentence, source) tuples.
            num_sources: Number of source texts (used to split results).

        Returns:
            List of score lists, one per sentence, each containing scores per source.
        """
        reranker = await self._get_reranker()
        model = await reranker._ensure_model()
        all_scores = await asyncio.to_thread(model.predict, all_pairs)

        # Split results: each sentence has num_sources scores
        result = []
        for i in range(0, len(all_scores), num_sources):
            result.append([float(s) for s in all_scores[i:i + num_sources]])
        return result

    async def verify(
        self,
        response: str,
        sources: list,
        similarity_threshold: float | None = None,
        remove_unsupported: bool | None = None,
    ) -> VerifiedResponse:
        """Verify a generated response against source chunks using cross-encoder.

        Args:
            response: The LLM-generated response text
            sources: List of source chunks (objects with .content attribute or strings)
            similarity_threshold: Override for VERIFICATION_SIMILARITY_THRESHOLD
            remove_unsupported: Override for VERIFICATION_REMOVE_UNSUPPORTED

        Returns:
            VerifiedResponse with verified text, citations, unsupported claims, and confidence
        """
        if not settings.verification_enabled:
            return VerifiedResponse(
                verified_text=response,
                citations=[],
                unsupported=[],
                confidence=1.0,
            )

        threshold = similarity_threshold if similarity_threshold is not None else settings.verification_similarity_threshold  # noqa: E501
        do_remove = remove_unsupported if remove_unsupported is not None else settings.verification_remove_unsupported  # noqa: E501

        # Extract source texts
        source_texts = []
        for src in sources:
            if hasattr(src, 'content'):
                source_texts.append(src.content)
            elif isinstance(src, str):
                source_texts.append(src)

        if not source_texts:
            logger.warning("No source texts provided for verification")
            return VerifiedResponse(
                verified_text=response,
                citations=[],
                unsupported=[],
                confidence=1.0,
            )

        # Split response into sentences
        sentences = self._split_sentences(response)

        if not sentences:
            return VerifiedResponse(
                verified_text=response,
                citations=[],
                unsupported=[],
                confidence=0.0,
            )

        # Parse existing citations
        citation_map = self._parse_citations(response)

        verified_sentences = []
        unsupported_sentences = []
        verified_citations = []
        scores = []

        # Batch all (sentence, source) pairs for single cross-encoder call
        all_pairs = [
            (sentence, src)
            for sentence in sentences
            for src in source_texts
        ]
        all_cross_scores = await self._score_all_cross_encoder(all_pairs, len(source_texts))

        for i, sentence in enumerate(sentences):
            sentence_citations = citation_map.get(i, [])

            # Validate citations: drop out-of-range indices with a warning
            valid_citations = []
            for c in sentence_citations:
                if 1 <= c <= len(source_texts):
                    valid_citations.append(c)
                else:
                    logger.warning(
                        f"Citation [Source {c}] in sentence {i} is out of range "
                        f"(only {len(source_texts)} sources available), removing"
                    )

            fixed_citations = []
            score = 0.0

            # Use pre-computed batch scores
            cross_scores = all_cross_scores[i]

            if valid_citations:
                best_match_score = float('-inf')
                best_match_idx = None
                for src_idx in valid_citations:
                    sim = cross_scores[src_idx - 1]
                    if sim >= threshold and sim > best_match_score:
                        best_match_score = sim
                        best_match_idx = src_idx

                if best_match_idx is not None:
                    fixed_citations = [best_match_idx]
                    score = best_match_score

            if not fixed_citations:
                best_idx = int(max(range(len(cross_scores)), key=lambda j: cross_scores[j]))
                best_score = cross_scores[best_idx]
                if best_score >= threshold:
                    fixed_citations = [best_idx + 1]
                    score = best_score

            if fixed_citations:
                verified_sentences.append(sentence)
                scores.append(score)
            elif do_remove:
                unsupported_sentences.append(sentence)
                scores.append(0.0)
            else:
                verified_sentences.append(sentence)
                unsupported_sentences.append(sentence)
                scores.append(0.0)

            verified_citations.append({
                "sentence": sentence,
                "source_indices": list(fixed_citations),
            })

        # Build verified text
        if verified_sentences:
            verified_text = " ".join(verified_sentences)
        else:
            verified_text = "I don't have enough information to answer this question."

        # Calculate overall confidence
        confidence = sum(scores) / len(scores) if scores else 0.0

        return VerifiedResponse(
            verified_text=verified_text,
            citations=verified_citations,
            unsupported=unsupported_sentences,
            confidence=confidence,
        )


# ---------------------------------------------------------------------------
# Parameter claim validation
# ---------------------------------------------------------------------------


def validate_parameter_claims(
    answer: str,
    context_chunks: list[dict],
) -> dict:
    """Check parameter claims in the generated answer against context chunk metadata.

    Cross-references any parameter names mentioned in the answer against the
    actual parameters found in the context chunks used for generation. Flags
    parameter names that appear in the answer but are not present in any chunk.

    Args:
        answer: The generated answer text to validate.
        context_chunks: Documentation chunks used to generate the answer.
            Each chunk is a dict that may contain a ``"metadata"`` key with a
            ``"parameters"`` list (each parameter dict has a ``"name"`` key).
            Some chunks may store parameters directly at the top level, or
            be parameter-kind chunks with a ``"name"`` in metadata.

    Returns:
        A :class:`QueryValidationResult` dict with keys:
        - ``is_valid`` (bool): True if no unsupported claims found.
        - ``unsupported_parameter_claims`` (list[str]): Parameter names
          mentioned in the answer but not found in any context chunk.
        - ``supported_parameter_claims`` (list[str]): Parameter names
          found both in the answer and in context chunks.
        - ``confidence`` (float): Ratio of supported claims to total
           claims found (0.0-1.0). 1.0 when no claims or no context.
    """
    # Edge case: empty answer or whitespace-only
    if not answer or not answer.strip():
        logger.debug("validate_parameter_claims: empty answer — skipping")
        return _valid_result()

    # Edge case: no context chunks to verify against
    if not context_chunks:
        logger.debug("validate_parameter_claims: no context chunks — skipping")
        return _valid_result()

    # 1. Extract canonical parameter names from all context chunks
    canonical_params = _extract_canonical_parameters(context_chunks)

    if not canonical_params:
        # No parameters defined in any chunk — cannot verify, pass
        logger.debug(
            "validate_parameter_claims: no parameters in context chunks — skipping"
        )
        return _valid_result()

    # 2. Find candidate parameter claims in the answer text
    claimed_params = _find_parameter_claims(answer, canonical_params)

    if not claimed_params:
        logger.debug("validate_parameter_claims: no parameter claims found in answer")
        return _valid_result()

    # 3. Classify each claim as supported or unsupported
    canonical_lower: set[str] = {p.lower() for p in canonical_params}

    supported: list[str] = []
    unsupported: list[str] = []
    for param in claimed_params:
        if param.lower() in canonical_lower:
            supported.append(param)
        else:
            unsupported.append(param)

    # 4. Compute confidence
    total_claims = len(supported) + len(unsupported)
    confidence = len(supported) / total_claims if total_claims > 0 else 1.0

    logger.debug(
        "validate_parameter_claims: %d supported, %d unsupported (confidence=%.4f)",
        len(supported),
        len(unsupported),
        confidence,
    )

    return {
        "is_valid": len(unsupported) == 0,
        "unsupported_parameter_claims": unsupported,
        "supported_parameter_claims": supported,
        "confidence": round(confidence, 4),
    }


def _valid_result() -> dict:
    """Return a pass-through valid result (empty claims, confidence=1.0)."""
    return {
        "is_valid": True,
        "unsupported_parameter_claims": [],
        "supported_parameter_claims": [],
        "confidence": 1.0,
    }


def _extract_canonical_parameters(context_chunks: list[dict]) -> set[str]:
    """Extract all known parameter names from the context chunks.

    Searches multiple locations where parameters may be stored:

    * ``chunk["metadata"]["parameters"]`` — list of parameter dicts on method
      chunks (the most common case).
    * ``chunk["metadata"]["name"]`` when ``kind == "parameter"`` — individual
      parameter-level chunks.
    * ``chunk["parameters"]`` — direct top-level key (fallback for some
      pipelines).
    * ``chunk["metadata"]["kind"] in ("record_field", "property")`` with a
      ``"name"`` — record fields and properties are also treated as parameters
      for validation purposes.

    Args:
        context_chunks: The list of context chunk dicts.

    Returns:
        A set of canonical (original-case) parameter names.
    """
    params: set[str] = set()

    if len(context_chunks) > 100:
        context_chunks = context_chunks[:100]

    for chunk in context_chunks:
        metadata = chunk.get("metadata")
        if isinstance(metadata, dict):
            # Most common: method chunks with a "parameters" list in metadata
            for p in metadata.get("parameters", []):
                if isinstance(p, dict) and p.get("name"):
                    params.add(p["name"])

            # Parameter-level chunks (individual parameter nodes)
            if metadata.get("kind") == "parameter" and metadata.get("name"):
                params.add(metadata["name"])

            # Record fields and properties — treat as parameter names
            kind = metadata.get("kind", "")
            if kind in ("record_field", "property") and metadata.get("name"):
                params.add(metadata["name"])

        # Top-level "parameters" key (fallback for some pipeline formats)
        for p in chunk.get("parameters", []):
            if isinstance(p, dict) and p.get("name"):
                params.add(p["name"])

    return params


def _find_parameter_claims(answer: str, canonical_params: set[str]) -> set[str]:
    answer = answer[:10000]
    """Find parameter names mentioned in the answer using heuristic patterns.

    Uses a series of regular expressions to detect likely parameter references:

    1. Backtick-quoted names directly adjacent to ``parameter``/``param``
       keywords (highest confidence).
    2. Double-quoted names adjacent to ``parameter``/``param`` keywords.
    3. ``the ``<name>`` parameter`` construction.
    4. Any backtick-quoted or double-quoted word that matches a known
       canonical parameter name (lower-confidence, used for catch-all).

    Args:
        answer: The generated answer text.
        canonical_params: Set of known parameter names for catch-all matching.

    Returns:
        A set of parameter name strings mentioned in the answer.
    """
    claims: set[str] = set()

    # -- High-confidence patterns: "parameter" keyword adjacency --

    # Pattern A: `` `name` parameter `` / `` `name` param ``
    for match in re.finditer(r'`(\w{1,100})`\s+(?:parameter|param)\b', answer, re.IGNORECASE):
        claims.add(match.group(1))

    # Pattern B: `` parameter `name` `` / `` param `name` ``
    for match in re.finditer(r'(?:parameter|param)\s+`(\w{1,100})`', answer, re.IGNORECASE):
        claims.add(match.group(1))

    # Pattern C: `` "name" parameter `` / `` "name" param ``
    for match in re.finditer(r'"(\w{1,100})"\s+(?:parameter|param)\b', answer, re.IGNORECASE):
        claims.add(match.group(1))

    # Pattern D: `` parameter "name" `` / `` param "name" ``
    for match in re.finditer(r'(?:parameter|param)\s+"(\w{1,100})"', answer, re.IGNORECASE):
        claims.add(match.group(1))

    # Pattern E: `` the `name` parameter ``
    for match in re.finditer(r'the\s+`(\w{1,100})`\s+parameter\b', answer, re.IGNORECASE):
        claims.add(match.group(1))

    # Pattern F: `` the "name" parameter ``
    for match in re.finditer(r'the\s+"(\w{1,100})"\s+parameter\b', answer, re.IGNORECASE):
        claims.add(match.group(1))

    # -- Lower-confidence catch-all: quoted words matching known params --

    canonical_lower: set[str] = {p.lower() for p in canonical_params}

    # Pattern G: Any backtick-quoted identifier matching a known param name
    for match in re.finditer(r'`([\w.]+)`', answer):
        candidate = match.group(1)
        if candidate.lower() in canonical_lower:
            claims.add(candidate)

    # Pattern H: Any double-quoted identifier matching a known param name
    for match in re.finditer(r'"([\w.]+)"', answer):
        candidate = match.group(1)
        if candidate.lower() in canonical_lower:
            claims.add(candidate)

    return claims
