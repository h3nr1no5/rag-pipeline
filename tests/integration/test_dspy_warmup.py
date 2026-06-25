"""Integration tests for DSPy LM warmup behaviour.

Covers Task 13.9 — verifies that the ``dspy_lm`` model entry in
``WarmupState`` transitions to ``"ready"`` when the LLM is available
and ``api_docs_enabled`` is ``True``.

The DSPy LM is an adapter that wraps the existing MLX LLM, so it should
become ready immediately (no download or lengthy initialisation) as long
as the LLM warmup has completed.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.services.warmup import warmup_models, get_warmup_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_embedder():
    """Clear the global embedder instance before each test."""
    import src.domain.services.embedding as emb_mod

    emb_mod.reset_embedder()
    yield
    emb_mod.reset_embedder()


# =========================================================================
# Task 13.9 — DSPy LM transitions to ready
# =========================================================================


@pytest.mark.asyncio
async def test_dspy_lm_ready_when_api_docs_enabled():
    """``dspy_lm`` becomes ``"ready"`` after warmup when
    ``api_docs_enabled=True``."""
    original_dspy = os.environ.get("API_DOCS_DSPY_ENABLED")
    os.environ["API_DOCS_DSPY_ENABLED"] = "true"
    try:
        mock_embedder = MagicMock()
        mock_embedder.get_dimension.return_value = 768

        mock_ce = MagicMock()
        mock_ce._ensure_model = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.api_docs_enabled = True

        mock_dspy_lm = MagicMock()

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
            patch(
                "src.domain.rag.api_docs.pipeline.lm_adapter.get_mlx_dspy_lm",
                return_value=mock_dspy_lm,
            ),
            patch("dspy.configure"),
        ):
            await warmup_models()
    finally:
        if original_dspy is not None:
            os.environ["API_DOCS_DSPY_ENABLED"] = original_dspy
        else:
            os.environ.pop("API_DOCS_DSPY_ENABLED", None)

    state = get_warmup_state()
    dspy_status = await state.get_status("dspy_lm")
    assert dspy_status is not None, "dspy_lm should be registered in WarmupState"
    assert dspy_status.status == "ready", (
        f"Expected dspy_lm status 'ready' but got '{dspy_status.status}'"
    )
    assert dspy_status.progress == 100


@pytest.mark.asyncio
async def test_dspy_lm_ready_when_api_docs_disabled():
    """``dspy_lm`` is marked ``"ready"`` even when ``api_docs_enabled=False``
    (it is simply not required)."""
    original_dspy = os.environ.get("API_DOCS_DSPY_ENABLED")
    os.environ["API_DOCS_DSPY_ENABLED"] = "true"
    try:
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
    finally:
        if original_dspy is not None:
            os.environ["API_DOCS_DSPY_ENABLED"] = original_dspy
        else:
            os.environ.pop("API_DOCS_DSPY_ENABLED", None)

    state = get_warmup_state()
    dspy_status = await state.get_status("dspy_lm")
    assert dspy_status is not None
    assert dspy_status.status == "ready"
    assert dspy_status.progress == 100
    # Message should indicate DSPy LM is not required
    assert dspy_status.message and "not required" in dspy_status.message.lower()


@pytest.mark.asyncio
async def test_dspy_lm_uses_dspy_configure_when_enabled():
    """When ``api_docs_enabled=True``, ``dspy.configure()`` is called with
    the MLX DSPy LM adapter."""
    original_dspy = os.environ.get("API_DOCS_DSPY_ENABLED")
    os.environ["API_DOCS_DSPY_ENABLED"] = "true"
    try:
        mock_embedder = MagicMock()
        mock_embedder.get_dimension.return_value = 768

        mock_ce = MagicMock()
        mock_ce._ensure_model = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.api_docs_enabled = True

        mock_dspy_lm = MagicMock()

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
            patch(
                "src.domain.rag.api_docs.pipeline.lm_adapter.get_mlx_dspy_lm",
                return_value=mock_dspy_lm,
            ) as mock_get_lm,
            patch("dspy.configure") as mock_dspy_configure,
        ):
            await warmup_models()
    finally:
        if original_dspy is not None:
            os.environ["API_DOCS_DSPY_ENABLED"] = original_dspy
        else:
            os.environ.pop("API_DOCS_DSPY_ENABLED", None)

    mock_get_lm.assert_called_once()
    mock_dspy_configure.assert_called_once_with(lm=mock_dspy_lm)
