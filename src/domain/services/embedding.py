import os
import time
import logging
from ...domain.ports.embedder import Embedder
from ...core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Suppress tokenizer parallelism multiprocessing warning; must be set before sentence_transformers import (lazy-loaded in __init__)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

_embedder_instance = None
_embedder_load_time = None


class SentenceTransformerEmbedder(Embedder):
    def __init__(self):
        start_time = time.time()
        logger.info(f"Loading embedding model: {settings.embedding_model}")
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(settings.embedding_model)
            self._dimension = self.model.get_sentence_embedding_dimension()
            load_time = time.time() - start_time
            logger.info(f"Embedding model loaded successfully in {load_time:.2f}s, dimension: {self._dimension}")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {type(e).__name__}: {e}")
            raise

    async def embed_text(self, text: str) -> list[float]:
        import asyncio
        start_time = time.time()
        try:
            if not text or not text.strip():
                logger.warning("Empty text provided for embedding")
                return [0.0] * self._dimension
            
            embedding = await asyncio.to_thread(self.model.encode, text)
            duration = time.time() - start_time
            logger.debug(f"Embedded text ({len(text)} chars) in {duration:.3f}s")
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Failed to embed text: {type(e).__name__}: {e}")
            raise

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        import asyncio
        start_time = time.time()
        try:
            if not texts:
                return []
            
            texts = [t if t and t.strip() else " " for t in texts]
            
            embeddings = await asyncio.to_thread(
                self.model.encode, 
                texts, 
                batch_size=settings.embedding_batch_size,
                show_progress_bar=False,
            )
            duration = time.time() - start_time
            logger.info(f"Embedded {len(texts)} texts in {duration:.3f}s ({len(texts)/duration:.1f} texts/sec)")
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Failed to embed texts: {type(e).__name__}: {e}")
            raise

    def get_model_name(self) -> str:
        return settings.embedding_model

    def get_dimension(self) -> int:
        return self._dimension


def normalize_scores(scores: list[float]) -> list[float]:
    """Apply min-max normalization to a list of scores, producing [0, 1] range.

    If all scores are identical, returns them unchanged (avoids division by zero).
    If the list is empty, returns an empty list.
    """
    if not scores:
        return []
    min_s = min(scores)
    max_s = max(scores)
    if max_s - min_s < 1e-10:
        return scores
    return [(s - min_s) / (max_s - min_s) for s in scores]


def normalize_embedding(embedding: list[float]) -> list[float]:
    """L2-normalize an embedding vector in-place so it has unit norm.

    If the vector is already unit-length (within tolerance), returns it unchanged.
    If the norm is zero (all-zeros vector), returns it unchanged.
    """
    import math
    norm = math.sqrt(sum(x * x for x in embedding))
    if norm < 1e-10 or abs(norm - 1.0) < 1e-6:
        return embedding
    return [x / norm for x in embedding]


async def get_embedder() -> SentenceTransformerEmbedder:
    global _embedder_instance, _embedder_load_time
    if _embedder_instance is None:
        start_time = time.time()
        logger.info("Creating embedder instance...")
        _embedder_instance = SentenceTransformerEmbedder()
        _embedder_load_time = time.time() - start_time
        logger.info(f"Embedder ready (loaded in {_embedder_load_time:.2f}s)")
    return _embedder_instance


def get_embedder_stats() -> dict:
    return {
        "model": settings.embedding_model,
        "loaded": _embedder_instance is not None,
        "load_time": _embedder_load_time,
        "dimension": _embedder_instance.get_dimension() if _embedder_instance else None,
    }


def reset_embedder():
    global _embedder_instance, _embedder_load_time
    logger.info("Resetting embedder instance")
    _embedder_instance = None
    _embedder_load_time = None
