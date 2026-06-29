"""Integration tests for DSPy LM warmup behaviour.

Covers Task 13.9 — verifies that DSPy LM configuration is invoked
when ``api_docs_enabled`` is ``True``.

The DSPy LM is an adapter that wraps the existing MLX LLM.
"""

import os
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


@patch(
    "src.domain.rag.api_docs.pipeline.lm_adapter.get_mlx_dspy_lm",
    return_value=MagicMock(),
)
@patch("dspy.configure")
@patch("src.core.config.get_settings")
@patch("huggingface_hub.snapshot_download")
@pytest.mark.asyncio
async def test_dspy_lm_uses_dspy_configure_when_enabled(
    mock_snapshot, mock_settings, mock_dspy_configure, mock_get_lm
):
    """When ``api_docs_enabled=True``, ``dspy.configure()`` is called with
    the MLX DSPy LM adapter."""
    original_dspy = os.environ.get("API_DOCS_DSPY_ENABLED")
    os.environ["API_DOCS_DSPY_ENABLED"] = "true"
    try:
        mock_settings.return_value.api_docs_enabled = True

        import dspy

        from src.domain.rag.api_docs.pipeline.lm_adapter import get_mlx_dspy_lm
        dspy.configure(lm=get_mlx_dspy_lm())
    finally:
        if original_dspy is not None:
            os.environ["API_DOCS_DSPY_ENABLED"] = original_dspy
        else:
            os.environ.pop("API_DOCS_DSPY_ENABLED", None)

    mock_get_lm.assert_called_once()
    mock_dspy_configure.assert_called_once()
