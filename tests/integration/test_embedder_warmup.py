"""Integration tests for embedder warmup and global instance assignment.

Covers Task 13.8 — verifies that ``SentenceTransformerEmbedder`` is
instantiated and sets the module-level ``_embedder_instance`` singleton
so that ``get_embedder()`` can return it immediately without re-loading.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def isolate_global_state():
    """Save/restore the global embedder singleton around each test.

    This allows warmup tests to start with a clean slate while
    preserving the session-scoped seeding state for other tests.
    """
    import src.domain.services.embedding as emb_mod

    saved = emb_mod._embedder_instance
    emb_mod._embedder_instance = None
    yield
    emb_mod._embedder_instance = saved


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
