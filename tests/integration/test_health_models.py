"""Integration tests for ``GET /health/models``.

Covers Task 13.9 — the health endpoint that exposes per-model warmup state.

Since the app lifespan (and therefore ``warmup_models()``) does not run during
synchronous ``TestClient`` usage, each test seeds the ``WarmupState``
singleton with synthetic entries before making requests.

The database fixture (``setup_test_db``) runs automatically from the root
conftest so that ``app``-level schema checks can succeed.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.domain.services.warmup import WarmupState, ModelStatus, get_warmup_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL_NAMES = ("cross_encoder", "llm", "embedder", "dspy_lm")


def _seed_default_state():
    """Seed the warmup singleton with all 4 model entries (default status)."""
    state = get_warmup_state()
    state._models.clear()
    for name in _MODEL_NAMES:
        state._models[name] = ModelStatus(model=name)


def _seed_custom(**overrides: dict):
    """Seed the warmup singleton with custom model entries.

    Parameters
    ----------
    **overrides:
        Mapping of ``model_name → dict`` of attribute overrides.
        Example: ``llm={"status": "error", "error": "real msg"}``
    """
    state = get_warmup_state()
    state._models.clear()
    for name in _MODEL_NAMES:
        kwargs = overrides.get(name, {})
        state._models[name] = ModelStatus(model=name, **kwargs)


# =============================================================================
# Tests
# =============================================================================


class TestHealthModelsEndpoint:
    """Verifies the ``/health/models`` response structure."""

    def test_health_models_returns_all_four_models(self):
        """The endpoint returns entries for all 4 expected model keys."""
        _seed_default_state()
        client = TestClient(app)
        response = client.get("/api/v1/health/models")
        assert response.status_code == 200

        data = response.json()
        model_keys = set(_MODEL_NAMES)
        assert model_keys.issubset(data.keys()), (
            f"Expected keys {model_keys} but got {set(data.keys())}"
        )

    def test_each_model_entry_has_required_fields(self):
        """Every model entry contains the expected fields."""
        _seed_default_state()
        client = TestClient(app)
        response = client.get("/api/v1/health/models")
        assert response.status_code == 200

        data = response.json()
        required_fields = {"status", "model", "progress", "error", "message"}

        for name in _MODEL_NAMES:
            entry = data.get(name)
            assert entry is not None, f"Missing entry for {name}"
            missing = required_fields - set(entry.keys())
            assert not missing, f"Entry '{name}' missing fields: {missing}"

    def test_health_models_returns_loading_status_by_default(self):
        """Models that haven't completed warmup show 'loading' status."""
        _seed_default_state()
        client = TestClient(app)
        response = client.get("/api/v1/health/models")
        assert response.status_code == 200

        data = response.json()
        for name in _MODEL_NAMES:
            assert data[name]["status"] == "loading"
            assert data[name]["progress"] == 0
            assert data[name]["error"] is None

    def test_health_models_reflects_ready_status(self):
        """Models that finished warmup show 'ready' with 100 % progress."""
        _seed_custom(
            llm={"status": "ready", "progress": 100},
            cross_encoder={"status": "ready", "progress": 100},
            embedder={"status": "ready", "progress": 100},
            dspy_lm={"status": "ready", "progress": 100},
        )
        client = TestClient(app)
        response = client.get("/api/v1/health/models")
        assert response.status_code == 200

        data = response.json()
        assert data["llm"]["status"] == "ready"
        assert data["llm"]["progress"] == 100
        assert data["cross_encoder"]["status"] == "ready"
        assert data["embedder"]["status"] == "ready"
        assert data["dspy_lm"]["status"] == "ready"

    def test_health_models_error_is_sanitized(self):
        """The endpoint uses ``sanitize_errors=True``, hiding real error msgs."""
        _seed_custom(
            llm={"status": "error", "error": "CUDA out of memory on device 0"},
        )
        client = TestClient(app)
        response = client.get("/api/v1/health/models")
        assert response.status_code == 200

        data = response.json()
        # The raw error must be replaced by the generic message
        assert data["llm"]["error"] == "Model failed to load"

    def test_health_models_entry_includes_message_field(self):
        """The ``message`` field is preserved in the serialised output."""
        _seed_custom(
            llm={"status": "loading", "message": "Downloading model..."},
        )
        client = TestClient(app)
        response = client.get("/api/v1/health/models")
        assert response.status_code == 200

        data = response.json()
        assert data["llm"]["message"] == "Downloading model..."
