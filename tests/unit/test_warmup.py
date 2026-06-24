"""Unit tests for WarmupState model warmup tracking."""

import asyncio

import pytest
import pytest_asyncio
from src.domain.services.warmup import get_warmup_state, WarmupState, ModelStatus


@pytest_asyncio.fixture(autouse=True)
async def reset_warmup_state():
    """Reset WarmupState singleton to defaults before each test."""
    state = get_warmup_state()
    await state.update("cross_encoder", status="loading", progress=0, error=None, model="")
    await state.update("llm", status="loading", progress=0, error=None, model="")
    await state.update("embedder", status="loading", progress=0, error=None, model="")
    await state.update("dspy_lm", status="loading", progress=0, error=None, model="")
    yield


class TestWarmupState:
    """Tests for WarmupState singleton, updates, and serialization."""

    # ── Singleton ─────────────────────────────────────────────────────

    async def test_warmup_state_singleton(self):
        """get_warmup_state() always returns the same instance."""
        state1 = get_warmup_state()
        state2 = get_warmup_state()
        assert state1 is state2

    # ── Default state ─────────────────────────────────────────────────

    async def test_default_initial_state(self):
        """Fresh WarmupState has all models in 'loading' status."""
        state = get_warmup_state()
        data = await state.to_dict(sanitize_errors=False)

        for model in ("cross_encoder", "llm", "embedder", "dspy_lm"):
            assert data[model]["status"] == "loading"
            assert data[model]["progress"] == 0
            assert data[model]["error"] is None

    # ── Update methods ────────────────────────────────────────────────

    async def test_update_cross_encoder(self):
        """Updating cross-encoder fields is reflected in to_dict()."""
        state = get_warmup_state()
        await state.update("cross_encoder", status="ready", progress=100)

        data = await state.to_dict(sanitize_errors=False)
        assert data["cross_encoder"]["status"] == "ready"
        assert data["cross_encoder"]["progress"] == 100

    async def test_update_llm(self):
        """Updating LLM fields is reflected in to_dict()."""
        state = get_warmup_state()
        await state.update("llm", status="error", error="Test error")

        data = await state.to_dict(sanitize_errors=False)
        assert data["llm"]["status"] == "error"
        assert data["llm"]["error"] == "Test error"

    async def test_partial_update_cross_encoder(self):
        """Partial update does not reset fields that were not touched."""
        state = get_warmup_state()
        await state.update("cross_encoder", model="ce-v1")
        await state.update("cross_encoder", progress=50)

        data = await state.to_dict(sanitize_errors=False)
        assert data["cross_encoder"]["model"] == "ce-v1"
        assert data["cross_encoder"]["progress"] == 50
        assert data["cross_encoder"]["status"] == "loading"  # unchanged

    async def test_partial_update_llm(self):
        """Partial update does not reset fields that were not touched."""
        state = get_warmup_state()
        await state.update("llm", model="llm-v2")
        await state.update("llm", progress=75)

        data = await state.to_dict(sanitize_errors=False)
        assert data["llm"]["model"] == "llm-v2"
        assert data["llm"]["progress"] == 75
        assert data["llm"]["error"] is None  # unchanged

    # ── Error sanitization ────────────────────────────────────────────

    async def test_error_sanitization(self):
        """to_dict(sanitize_errors=True) replaces real error messages."""
        state = get_warmup_state()
        await state.update("llm", 
            status="error", error="Connection refused: /path/to/model"
        )

        # sanitize_errors=True (default)
        data = await state.to_dict()
        assert data["llm"]["error"] == "Model failed to load"

        # sanitize_errors=False
        data = await state.to_dict(sanitize_errors=False)
        assert data["llm"]["error"] == "Connection refused: /path/to/model"

    async def test_error_sanitization_cross_encoder(self):
        """Cross-encoder errors are also sanitized."""
        state = get_warmup_state()
        await state.update("cross_encoder", 
            status="error", error="CUDA out of memory"
        )

        data = await state.to_dict()
        assert data["cross_encoder"]["error"] == "Model failed to load"

        data = await state.to_dict(sanitize_errors=False)
        assert data["cross_encoder"]["error"] == "CUDA out of memory"

    async def test_sanitize_skips_none_errors(self):
        """sanitize_errors does not touch errors that are already None."""
        state = get_warmup_state()
        # All models start with error=None
        data = await state.to_dict(sanitize_errors=True)
        for model in ("cross_encoder", "llm", "embedder", "dspy_lm"):
            assert data[model]["error"] is None

    # ── Properties ────────────────────────────────────────────────────

    async def test_all_ready_both_loading(self):
        """all_ready is False when both models are still loading."""
        state = get_warmup_state()
        assert not state.all_ready

    async def test_all_ready_one_ready(self):
        """all_ready is False when only one model is ready."""
        state = get_warmup_state()
        await state.update("cross_encoder", status="ready", progress=100)
        assert not state.all_ready

    async def test_all_ready_both_ready(self):
        """all_ready is True when all models are ready."""
        state = get_warmup_state()
        await state.update("cross_encoder", status="ready", progress=100)
        await state.update("llm", status="ready", progress=100)
        await state.update("embedder", status="ready", progress=100)
        await state.update("dspy_lm", status="ready", progress=100)
        assert state.all_ready

    async def test_all_ready_one_error(self):
        """all_ready is False when one model errored."""
        state = get_warmup_state()
        await state.update("cross_encoder", status="ready", progress=100)
        await state.update("llm", status="error", error="Failed")
        assert not state.all_ready

    async def test_any_loading_default(self):
        """any_loading is True when both models start as 'loading'."""
        state = get_warmup_state()
        assert state.any_loading

    async def test_any_loading_one_ready(self):
        """any_loading is True when at least one model is still loading."""
        state = get_warmup_state()
        await state.update("cross_encoder", status="ready", progress=100)
        # LLM still loading
        assert state.any_loading

    async def test_any_loading_both_ready(self):
        """any_loading is False when all models are ready."""
        state = get_warmup_state()
        await state.update("cross_encoder", status="ready", progress=100)
        await state.update("llm", status="ready", progress=100)
        await state.update("embedder", status="ready", progress=100)
        await state.update("dspy_lm", status="ready", progress=100)
        assert not state.any_loading

    async def test_any_loading_all_error(self):
        """any_loading is False when all models have errored."""
        state = get_warmup_state()
        await state.update("cross_encoder", status="error", error="Fail A")
        await state.update("llm", status="error", error="Fail B")
        await state.update("embedder", status="error", error="Fail C")
        await state.update("dspy_lm", status="error", error="Fail D")
        assert not state.any_loading

    # ── Model names ───────────────────────────────────────────────────

    async def test_model_names(self):
        """Model names are preserved in to_dict()."""
        state = get_warmup_state()
        await state.update("cross_encoder", model="cross-encoder-v1", progress=50)
        await state.update("llm", model="llm-42", progress=50)
        await state.update("embedder", model="all-mpnet-base-v2", progress=50)
        await state.update("dspy_lm", model="dspy-adapter", progress=50)

        data = await state.to_dict(sanitize_errors=False)
        assert data["cross_encoder"]["model"] == "cross-encoder-v1"
        assert data["llm"]["model"] == "llm-42"
        assert data["embedder"]["model"] == "all-mpnet-base-v2"
        assert data["dspy_lm"]["model"] == "dspy-adapter"

    # ── Concurrent updates ────────────────────────────────────────────

    async def test_concurrent_updates(self):
        """Concurrent updates to different models are safe."""
        state = get_warmup_state()

        async def update_ce():
            for i in range(10):
                await state.update("cross_encoder", progress=i * 10)

        async def update_llm_task():
            for i in range(10):
                await state.update("llm", progress=i * 10)

        await asyncio.gather(update_ce(), update_llm_task())

        data = await state.to_dict(sanitize_errors=False)
        assert data["cross_encoder"]["progress"] == 90
        assert data["llm"]["progress"] == 90

    async def test_concurrent_updates_same_model(self):
        """Concurrent updates to the same model are serialised by the lock."""
        state = get_warmup_state()

        async def writer_a():
            for i in range(5):
                await state.update("cross_encoder", progress=i * 10)

        async def writer_b():
            for i in range(5, 10):
                await state.update("cross_encoder", progress=i * 10)

        await asyncio.gather(writer_a(), writer_b())

        data = await state.to_dict(sanitize_errors=False)
        # Either writer_a or writer_b goes last; final progress should be
        # one of the terminal values (40 or 90), depending on ordering.
        assert data["cross_encoder"]["progress"] in (40, 90)

    # ── to_dict / serialization ───────────────────────────────────────

    async def test_to_dict_structure(self):
        """to_dict() returns the expected keys for all models."""
        state = get_warmup_state()
        data = await state.to_dict()

        for key in ("cross_encoder", "llm", "embedder", "dspy_lm"):
            assert key in data
            assert "status" in data[key]
            assert "model" in data[key]
            assert "progress" in data[key]
            assert "error" in data[key]
            assert "message" in data[key]

    async def test_to_dict_no_mutation(self):
        """to_dict() does not mutate internal state."""
        state = get_warmup_state()
        await state.update("cross_encoder", error="hidden error")

        data = await state.to_dict(sanitize_errors=True)
        assert data["cross_encoder"]["error"] == "Model failed to load"

        # Internal state should still hold the original error
        status = await state.get_status("cross_encoder")
        assert status is not None
        assert status.error == "hidden error"

    # ── ModelStatus dataclass ──────────────────────────────────────────

    async def test_model_status_defaults(self):
        """ModelStatus dataclass has correct default values."""
        status = ModelStatus()
        assert status.model == ""
        assert status.status == "loading"
        assert status.progress == 0
        assert status.error is None

    async def test_model_status_custom(self):
        """ModelStatus dataclass accepts custom values."""
        status = ModelStatus(model="m1", status="ready", progress=100, error=None)
        assert status.model == "m1"
        assert status.status == "ready"
        assert status.progress == 100
        assert status.error is None
