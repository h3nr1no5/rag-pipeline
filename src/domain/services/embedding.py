import asyncio
import logging
import math
import os
import threading
import time
from typing import Any

from ...core.config import get_settings
from ...core.logging import log_structured
from ...domain.ports.embedder import Embedder

logger = logging.getLogger(__name__)

settings = get_settings()

# Suppress tokenizer parallelism multiprocessing warning; must be set before sentence_transformers import (lazy-loaded in __init__)  # noqa: E501
os.environ["TOKENIZERS_PARALLELISM"] = "false"

_embedder_instance = None
_embedder_load_time = None
_embedder_lock = threading.Lock()


class SentenceTransformerEmbedder(Embedder):
    def __init__(self):
        start_time = time.time()
        logger.debug(f"Loading embedding model: {settings.embedding_model}")
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(settings.embedding_model)
            self._dimension = self.model.get_sentence_embedding_dimension()
            load_time = time.time() - start_time
            logger.debug(f"Embedding model loaded successfully in {load_time:.2f}s, dimension: {self._dimension}")  # noqa: E501
        except Exception as e:
            logger.error(f"Failed to load embedding model: {type(e).__name__}: {e}")
            raise

    async def embed_text(self, text: str) -> list[float]:
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
            logger.info(f"Embedded {len(texts)} texts in {duration:.3f}s ({len(texts)/duration:.1f} texts/sec)")  # noqa: E501
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
    norm = math.sqrt(sum(x * x for x in embedding))
    if norm < 1e-10 or abs(norm - 1.0) < 1e-6:
        return embedding
    return [x / norm for x in embedding]


def validate_embedding(embedding: Any, expected_dim: int, chunk_id: str = "unknown") -> tuple[bool, str]:  # noqa: E501
    """Validate a chunk embedding vector.

    Checks performed:
    - None / null
    - Not a list or tuple type
    - Different length than expected_dim (dimension mismatch)
    - Contains NaN values
    - Contains Inf or -Inf values

    Returns (is_valid: bool, reason: str) where reason is empty if valid,
    or a description of the validation failure.
    """
    if embedding is None:
        return False, "embedding is None"
    if not isinstance(embedding, (list, tuple)):
        return False, f"embedding type is {type(embedding).__name__}, expected list or tuple"
    if len(embedding) != expected_dim:
        return False, f"embedding dimension {len(embedding)} does not match expected dimension {expected_dim}"  # noqa: E501
    if any(not isinstance(v, (int, float)) or (v != v) for v in embedding):
        return False, "embedding contains NaN or non-numeric values"
    if any(abs(v) == float("inf") for v in embedding):
        return False, "embedding contains infinite values"
    return True, ""


def _load_embedder_sync() -> SentenceTransformerEmbedder:
    """Synchronous embedder loader with double-checked locking (loop-agnostic).

    Mirrors MLXLLM._ensure_model_loaded() pattern to avoid cross-event-loop
    RuntimeError when called via asyncio.to_thread().
    """
    global _embedder_instance, _embedder_load_time
    if _embedder_instance is None:
        with _embedder_lock:
            if _embedder_instance is None:
                start_time = time.time()
                _embedder_instance = SentenceTransformerEmbedder()
                _embedder_load_time = time.time() - start_time
                log_structured("src.domain.services.embedding", "init",
                    model=settings.embedding_model,
                    load_time_s=round(_embedder_load_time, 2),
                    dimension=_embedder_instance.get_dimension())
    return _embedder_instance


async def get_embedder() -> SentenceTransformerEmbedder:
    """Get or create the SentenceTransformerEmbedder singleton.

    Delegates to synchronous _load_embedder_sync() via asyncio.to_thread()
    on first call to avoid blocking the event loop.
    """
    if _embedder_instance is None:
        return await asyncio.to_thread(_load_embedder_sync)
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
