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

            # Score sentence against all source texts using cross-encoder
            cross_scores = await self._score_with_cross_encoder(sentence, source_texts)

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
