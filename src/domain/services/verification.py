"""Post-generation response verification for RAG pipelines.

Verifies each sentence in the generated response against source chunks
using embedding cosine similarity. Unsupported claims can be removed or flagged.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

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
    
    Uses embedding cosine similarity: each sentence is embedded and compared
    against all source chunk embeddings. Sentences below a configurable threshold
    are removed or flagged.
    """
    
    def __init__(self):
        self._embedder = None
    
    async def _get_embedder(self):
        """Get or create the embedder instance."""
        if self._embedder is None:
            from .embedding import get_embedder
            self._embedder = await get_embedder()
        return self._embedder
    
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
    
    async def _find_best_source_match(
        self, sentence: str, source_embeddings: list[list[float]], threshold: float
    ) -> Optional[int]:
        """Find the best matching source chunk for a sentence.
        
        Args:
            sentence: The sentence to match.
            source_embeddings: Pre-computed embeddings for all source texts.
            threshold: Minimum similarity score threshold.
            
        Returns the source index (1-based) if similarity >= threshold, else None.
        """
        embedder = await self._get_embedder()
        
        # Embed the sentence
        sentence_embedding = await embedder.embed_text(sentence)
        
        # Compute cosine similarities against pre-computed source embeddings
        import numpy as np
        
        sentence_vec = np.array(sentence_embedding)
        source_vecs = np.array(source_embeddings)
        
        # Normalize
        sentence_norm = sentence_vec / (np.linalg.norm(sentence_vec) + 1e-10)
        source_norms = source_vecs / (np.linalg.norm(source_vecs, axis=1, keepdims=True) + 1e-10)
        
        # Cosine similarity
        similarities = np.dot(source_norms, sentence_norm)
        
        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])
        
        if best_score >= threshold:
            return best_idx + 1  # 1-based source index
        return None
    
    async def verify(
        self,
        response: str,
        sources: list,
        similarity_threshold: Optional[float] = None,
        remove_unsupported: Optional[bool] = None,
    ) -> VerifiedResponse:
        """Verify a generated response against source chunks.
        
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
        
        threshold = similarity_threshold or settings.verification_similarity_threshold
        do_remove = remove_unsupported if remove_unsupported is not None else settings.verification_remove_unsupported
        
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
        
        # Pre-compute source embeddings once (avoids re-embedding per sentence)
        embedder = await self._get_embedder()
        source_embeddings = await embedder.embed_texts(source_texts)
        
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
            
            if source_embeddings:
                # Embed the sentence once for similarity computation
                embedder = await self._get_embedder()
                sentence_embedding = await embedder.embed_text(sentence)
                import numpy as np
                sentence_vec = np.array(sentence_embedding)
                sentence_norm = sentence_vec / (np.linalg.norm(sentence_vec) + 1e-10)
                source_vecs = np.array(source_embeddings)
                source_norms = source_vecs / (np.linalg.norm(source_vecs, axis=1, keepdims=True) + 1e-10)
                similarities = np.dot(source_norms, sentence_norm)  # (num_sources,)
                
                if valid_citations:
                    # Verify each cited source via similarity against its embedding
                    best_match_score = 0.0
                    best_match_idx = None
                    for src_idx in valid_citations:
                        sim = float(similarities[src_idx - 1])
                        if sim >= threshold and sim > best_match_score:
                            best_match_score = sim
                            best_match_idx = src_idx
                    
                    if best_match_idx is not None:
                        fixed_citations = [best_match_idx]
                        score = best_match_score
                
                if not fixed_citations:
                    # Retroactive matching: find best source among all
                    best_idx = int(np.argmax(similarities))
                    best_score = float(similarities[best_idx])
                    if best_score >= threshold:
                        fixed_citations = [best_idx + 1]  # 1-based
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
                "source_indices": list(fixed_citations),  # Copy to avoid mutation issues
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
