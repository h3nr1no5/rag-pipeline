"""Integration tests for embedder warmup and global instance assignment.

Covers Task 13.8 — verifies that ``SentenceTransformerEmbedder`` is
instantiated and sets the module-level ``_embedder_instance`` singleton
so that ``get_embedder()`` can return it immediately without re-loading.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_embedder():
    """Clear the global embedder instance before each test."""
    import src.domain.services.embedding as emb_mod

    emb_mod.reset_embedder()
    yield
    emb_mod.reset_embedder()


@pytest.mark.asyncio
async def test_embedder_warmup_sets_global_instance():
    """After loading, ``_embedder_instance`` is the same object
    that ``SentenceTransformerEmbedder()`` returned."""
    import src.domain.services.embedding as emb_mod

    mock_embedder = MagicMock()
    mock_embedder.get_dimension.return_value = 768

    with patch(
        "src.domain.services.embedding.SentenceTransformerEmbedder",
        return_value=mock_embedder,
    ):
        embedder = emb_mod.SentenceTransformerEmbedder()
        emb_mod._embedder_instance = embedder

    assert emb_mod._embedder_instance is mock_embedder, (
        "embedder should be assigned to module-level _embedder_instance"
    )


@pytest.mark.asyncio
async def test_embedder_warmup_instance_returned_by_get_embedder():
    """After setting the singleton, ``get_embedder()`` returns the pre-loaded instance."""
    import src.domain.services.embedding as emb_mod

    mock_embedder = MagicMock()
    mock_embedder.get_dimension.return_value = 768

    with patch(
        "src.domain.services.embedding.SentenceTransformerEmbedder",
        return_value=mock_embedder,
    ):
        embedder = emb_mod.SentenceTransformerEmbedder()
        emb_mod._embedder_instance = embedder

    loaded = await emb_mod.get_embedder()
    assert loaded is mock_embedder
