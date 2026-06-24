"""Integration tests for embedder warmup and global instance assignment.

Covers Task 13.8 — verifies that ``warmup_models()`` instantiates
``SentenceTransformerEmbedder`` during warmup and sets the module-level
``_embedder_instance`` singleton so that ``get_embedder()`` can return
it immediately without re-loading.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.services.warmup import warmup_models, get_warmup_state


# ---------------------------------------------------------------------------
# Fixture: reset embedder singleton before each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_embedder():
    """Clear the global embedder instance before each test."""
    import src.domain.services.embedding as emb_mod

    emb_mod.reset_embedder()
    yield
    emb_mod.reset_embedder()


# ---------------------------------------------------------------------------
# Helper: mock all heavy model-loading dependencies so ``warmup_models()``
# runs synchronously (no real HuggingFace downloads, no 120s timeouts).
# ---------------------------------------------------------------------------


def _mock_all_warmup_deps(mock_embedder_instance=None):
    """Return a context manager that patches every heavy external dependency
    used by :func:`~src.domain.services.warmup.warmup_models`.

    Parameters
    ----------
    mock_embedder_instance:
        The object that ``SentenceTransformerEmbedder()`` should return.
        If ``None`` a plain ``MagicMock`` is used.
    """
    if mock_embedder_instance is None:
        mock_embedder_instance = MagicMock()
        mock_embedder_instance.get_dimension.return_value = 768

    mock_ce = MagicMock()
    mock_ce._ensure_model = AsyncMock()
    mock_settings = MagicMock()
    mock_settings.api_docs_enabled = False

    return patch.multiple(
        "src.domain.services.embedding",
        SentenceTransformerEmbedder=MagicMock(return_value=mock_embedder_instance),
    ), patch.multiple(
        "src.domain.services.retrieval_langchain",
        CrossEncoderReRanker=MagicMock(return_value=mock_ce),
    ), patch(
        "src.domain.services.llm.get_llm", new=AsyncMock()
    ), patch(
        "huggingface_hub.snapshot_download",
    ), patch(
        "src.core.config.get_settings", return_value=mock_settings
    )


# =========================================================================
# Task 13.8 — Embedder warmup sets global instance
# =========================================================================


@pytest.mark.asyncio
async def test_embedder_warmup_sets_global_instance():
    """After warmup completes, ``_embedder_instance`` is the same object
    that ``SentenceTransformerEmbedder()`` returned."""
    import src.domain.services.embedding as emb_mod

    mock_embedder = MagicMock()
    mock_embedder.get_dimension.return_value = 768

    mock_ce = MagicMock()
    mock_ce._ensure_model = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.api_docs_enabled = False

    with (
        patch(
            "src.domain.services.embedding.SentenceTransformerEmbedder",
            return_value=mock_embedder,
        ),
        patch(
            "src.domain.services.retrieval_langchain.CrossEncoderReRanker",
            return_value=mock_ce,
        ),
        patch("src.domain.services.llm.get_llm", new=AsyncMock()),
        patch("huggingface_hub.snapshot_download"),
        patch("src.core.config.get_settings", return_value=mock_settings),
    ):
        await warmup_models()

    assert emb_mod._embedder_instance is mock_embedder, (
        "warmup_models() should assign the SentenceTransformerEmbedder "
        "instance to module-level _embedder_instance"
    )
    assert emb_mod._embedder_load_time is not None, (
        "_embedder_load_time should be set after warmup"
    )


@pytest.mark.asyncio
async def test_embedder_warmup_updates_warmup_state():
    """After warmup, the WarmupState entry for 'embedder' shows 'ready'."""
    mock_ce = MagicMock()
    mock_ce._ensure_model = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.api_docs_enabled = False

    with (
        patch(
            "src.domain.services.embedding.SentenceTransformerEmbedder",
            return_value=MagicMock(),
        ),
        patch(
            "src.domain.services.retrieval_langchain.CrossEncoderReRanker",
            return_value=mock_ce,
        ),
        patch("src.domain.services.llm.get_llm", new=AsyncMock()),
        patch("huggingface_hub.snapshot_download"),
        patch("src.core.config.get_settings", return_value=mock_settings),
    ):
        await warmup_models()

    state = get_warmup_state()
    embedder_status = await state.get_status("embedder")
    assert embedder_status is not None
    assert embedder_status.status == "ready"
    assert embedder_status.progress == 100


@pytest.mark.asyncio
async def test_embedder_warmup_instance_returned_by_get_embedder():
    """After warmup, ``get_embedder()`` returns the pre-loaded instance."""
    import src.domain.services.embedding as emb_mod

    mock_embedder = MagicMock()
    mock_embedder.get_dimension.return_value = 768

    mock_ce = MagicMock()
    mock_ce._ensure_model = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.api_docs_enabled = False

    with (
        patch(
            "src.domain.services.embedding.SentenceTransformerEmbedder",
            return_value=mock_embedder,
        ),
        patch(
            "src.domain.services.retrieval_langchain.CrossEncoderReRanker",
            return_value=mock_ce,
        ),
        patch("src.domain.services.llm.get_llm", new=AsyncMock()),
        patch("huggingface_hub.snapshot_download"),
        patch("src.core.config.get_settings", return_value=mock_settings),
    ):
        await warmup_models()

    # get_embedder() should return the pre-loaded instance without re-creating
    loaded = await emb_mod.get_embedder()
    assert loaded is mock_embedder
