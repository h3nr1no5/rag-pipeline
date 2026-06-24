"""Unit tests for WarmupState — model readiness tracking singleton.

Tests cover the refactored generic ``update(model_name, **kwargs)`` API
introduced in Tasks 13.1–13.7:

- ``WarmupState`` singleton behaviour
- ``update()`` / ``get_status()`` for individual model entries
- ``to_dict()`` serialization with error sanitization
- ``all_ready`` and ``any_loading`` properties
- Concurrent update safety via internal ``asyncio.Lock``
"""

import asyncio

import pytest
from src.domain.services.warmup import WarmupState, ModelStatus, get_warmup_state


@pytest.fixture(autouse=True)
def reset_warmup():
    """Clear the WarmupState model registry before each test.

    Because ``WarmupState`` is a singleton (with a module-level reference
    cached in ``get_warmup_state()``), we clear the internal ``_models``
    dict directly to guarantee test isolation.
    """
    state = get_warmup_state()
    state._models.clear()


# =========================================================================
# Basic update / get_status
# =========================================================================


@pytest.mark.asyncio
async def test_update_creates_new_entry():
    """``update()`` on an unseen model name creates a fresh ``ModelStatus``."""
    state = get_warmup_state()
    await state.update("test_model", status="loading", progress=0)

    status = await state.get_status("test_model")
    assert status is not None
    assert status.status == "loading"
    assert status.progress == 0


@pytest.mark.asyncio
async def test_update_existing_entry():
    """Calling ``update()`` twice on the same model merges kwargs."""
    state = get_warmup_state()
    await state.update("test_model", status="loading", progress=50)
    await state.update("test_model", status="ready", progress=100)

    status = await state.get_status("test_model")
    assert status.status == "ready"
    assert status.progress == 100


@pytest.mark.asyncio
async def test_get_status_nonexistent():
    """``get_status()`` returns ``None`` for an unregistered name."""
    state = get_warmup_state()
    status = await state.get_status("nonexistent")
    assert status is None


@pytest.mark.asyncio
async def test_update_partial_preserves_other_fields():
    """Partial update does not reset fields that were not passed."""
    state = get_warmup_state()
    await state.update("m1", model="my-model", status="loading", progress=10)
    await state.update("m1", progress=50)

    status = await state.get_status("m1")
    assert status.model == "my-model"   # preserved
    assert status.progress == 50        # updated
    assert status.status == "loading"   # unchanged


# =========================================================================
# to_dict serialisation
# =========================================================================


@pytest.mark.asyncio
async def test_to_dict_returns_all_models():
    """``to_dict()`` contains an entry per registered model."""
    state = get_warmup_state()
    await state.update("model_a", status="ready", progress=100)
    await state.update("model_b", status="loading", progress=50)

    result = await state.to_dict()
    assert "model_a" in result
    assert "model_b" in result
    assert result["model_a"]["status"] == "ready"
    assert result["model_b"]["status"] == "loading"


@pytest.mark.asyncio
async def test_to_dict_sanitizes_errors():
    """``to_dict(sanitize_errors=True)`` replaces real error strings."""
    state = get_warmup_state()
    await state.update("test_model", status="error", error="Something bad happened")

    result = await state.to_dict(sanitize_errors=True)
    assert result["test_model"]["error"] == "Model failed to load"


@pytest.mark.asyncio
async def test_to_dict_returns_message_field():
    """``to_dict()`` includes the ``message`` field."""
    state = get_warmup_state()
    await state.update("test_model", status="ready", message="All good")

    result = await state.to_dict()
    assert result["test_model"]["message"] == "All good"


@pytest.mark.asyncio
async def test_to_dict_raw_errors():
    """``to_dict(sanitize_errors=False)`` preserves the original error."""
    state = get_warmup_state()
    await state.update("test_model", status="error", error="Real error")

    result = await state.to_dict(sanitize_errors=False)
    assert result["test_model"]["error"] == "Real error"


@pytest.mark.asyncio
async def test_to_dict_sanitize_skips_none():
    """``sanitize_errors`` does not touch errors that are already ``None``."""
    state = get_warmup_state()
    await state.update("test_model", status="ready")

    result = await state.to_dict(sanitize_errors=True)
    assert result["test_model"]["error"] is None


@pytest.mark.asyncio
async def test_to_dict_does_not_mutate_internal_state():
    """``to_dict(sanitize_errors=True)`` does not alter the stored error."""
    state = get_warmup_state()
    await state.update("test_model", status="error", error="hidden secret")

    _ = await state.to_dict(sanitize_errors=True)
    raw = await state.get_status("test_model")
    assert raw.error == "hidden secret"  # internal state unchanged


# =========================================================================
# all_ready property
# =========================================================================


@pytest.mark.asyncio
async def test_all_ready_empty():
    """``all_ready`` is ``False`` when no models are registered."""
    state = get_warmup_state()
    assert state.all_ready is False


@pytest.mark.asyncio
async def test_all_ready_true():
    """``all_ready`` is ``True`` when every registered model is 'ready'."""
    state = get_warmup_state()
    await state.update("m1", status="ready")
    await state.update("m2", status="ready")
    assert state.all_ready is True


@pytest.mark.asyncio
async def test_all_ready_one_loading():
    """``all_ready`` is ``False`` when at least one model is still loading."""
    state = get_warmup_state()
    await state.update("m1", status="ready")
    await state.update("m2", status="loading")
    assert state.all_ready is False


@pytest.mark.asyncio
async def test_all_ready_one_error():
    """``all_ready`` is ``False`` when a model has errored."""
    state = get_warmup_state()
    await state.update("m1", status="ready")
    await state.update("m2", status="error")
    assert state.all_ready is False


@pytest.mark.asyncio
async def test_all_ready_mixed():
    """Multiple models: only all-ready when every status is 'ready'."""
    state = get_warmup_state()
    await state.update("a", status="ready")
    await state.update("b", status="permanent_error")
    await state.update("c", status="loading")
    assert state.all_ready is False


# =========================================================================
# any_loading property
# =========================================================================


@pytest.mark.asyncio
async def test_any_loading_all_ready():
    """``any_loading`` is ``False`` when all models are 'ready'."""
    state = get_warmup_state()
    await state.update("m1", status="ready")
    assert state.any_loading is False


@pytest.mark.asyncio
async def test_any_loading_one_loading():
    """``any_loading`` is ``True`` when at least one model is 'loading'."""
    state = get_warmup_state()
    await state.update("m1", status="ready")
    await state.update("m2", status="loading")
    assert state.any_loading is True


@pytest.mark.asyncio
async def test_any_loading_error():
    """``any_loading`` is ``False`` when all models are in terminal states."""
    state = get_warmup_state()
    await state.update("m1", status="error")
    assert state.any_loading is False


@pytest.mark.asyncio
async def test_any_loading_empty():
    """``any_loading`` is ``False`` when no models are registered."""
    state = get_warmup_state()
    assert state.any_loading is False


# =========================================================================
# Singleton behaviour
# =========================================================================


def test_warmup_state_singleton():
    """``get_warmup_state()`` always returns the same object."""
    s1 = get_warmup_state()
    s2 = get_warmup_state()
    assert s1 is s2


# =========================================================================
# ModelStatus dataclass defaults
# =========================================================================


def test_model_status_defaults():
    """``ModelStatus()`` has sensible defaults."""
    s = ModelStatus()
    assert s.model == ""
    assert s.status == "loading"
    assert s.progress == 0
    assert s.error is None
    assert s.message == ""


def test_model_status_custom_values():
    """``ModelStatus(...)`` accepts and stores custom values."""
    s = ModelStatus(model="m1", status="ready", progress=100, error=None, message="done")
    assert s.model == "m1"
    assert s.status == "ready"
    assert s.progress == 100
    assert s.error is None
    assert s.message == "done"


# =========================================================================
# Concurrent updates (lock safety)
# =========================================================================


@pytest.mark.asyncio
async def test_concurrent_updates_different_models():
    """Concurrent updates to **different** models are safe."""
    state = get_warmup_state()

    async def updater(name):
        for i in range(10):
            await state.update(name, progress=(i + 1) * 10)

    await asyncio.gather(updater("a"), updater("b"), updater("c"))

    assert (await state.get_status("a")) is not None
    assert (await state.get_status("b")) is not None
    assert (await state.get_status("c")) is not None


@pytest.mark.asyncio
async def test_concurrent_updates_same_model():
    """Concurrent updates to the *same* model are serialised by the lock."""
    state = get_warmup_state()

    async def writer_low():
        for i in range(5):
            await state.update("shared", progress=i * 10)

    async def writer_high():
        for i in range(5, 10):
            await state.update("shared", progress=i * 10)

    await asyncio.gather(writer_low(), writer_high())

    final = await state.get_status("shared")
    # Either writer_low or writer_high goes last — final progress should be
    # one of the terminal values (40 or 90).
    assert final.progress in (40, 90)


@pytest.mark.asyncio
async def test_concurrent_get_status_and_update():
    """Reading state via ``get_status()`` does not block updates forever."""
    state = get_warmup_state()
    await state.update("x", progress=0)

    async def reader():
        for _ in range(20):
            await state.get_status("x")

    async def writer():
        for i in range(20):
            await state.update("x", progress=i * 5)

    await asyncio.gather(reader(), writer())
    final = await state.get_status("x")
    assert final.progress == 95  # 19 * 5
