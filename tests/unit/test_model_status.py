"""Unit tests for ``model_status_banner()`` in ``client/components/model_status.py``.

Covers Tasks 16.1, 16.2, and 16.3:

- **16.1**: Unit tests covering early-exit paths, HTTP 200 variations
  (all ready, embedder loading, permanent error, mixed statuses), and
  ``requests.RequestException`` handling.
- **16.2**: Verifies the function makes an HTTP ``GET`` to the correct
  ``/health/models`` URL when called with a real API base URL.
- **16.3**: Verifies the ``embedder_ready`` return value correctly reflects
  the embedder's readiness from the backend response.

**Task 16.4** (backend 503 for document upload when embedder is loading)
is already covered by ``tests/integration/test_document_gate.py`` —
see ``test_upload_document_returns_503_when_embedder_loading`` and friends.
"""

from unittest.mock import MagicMock, patch

import pytest

from client.components.model_status import model_status_banner

# ---------------------------------------------------------------------------
# Shared response payloads
# ---------------------------------------------------------------------------

_ALL_READY = {
    "cross_encoder": {
        "status": "ready", "progress": 100,
        "model": "cross-encoder/ms-marco-MiniLM-L-12-v2",
        "message": "Ready",
    },
    "llm": {
        "status": "ready", "progress": 100,
        "model": "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
        "message": "Ready",
    },
    "embedder": {
        "status": "ready", "progress": 100,
        "model": "sentence-transformers/all-mpnet-base-v2",
        "message": "Ready",
    },
    "dspy_lm": {
        "status": "ready", "progress": 100,
        "model": "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
        "message": "Ready",
    },
}

_EMBEDDER_LOADING = {
    "cross_encoder": {"status": "ready", "progress": 100},
    "llm": {"status": "ready", "progress": 100},
    "embedder": {"status": "loading", "progress": 45, "message": "Loading model weights..."},
    "dspy_lm": {"status": "ready", "progress": 100},
}

_EMBEDDER_PERMANENT_ERROR = {
    "cross_encoder": {"status": "ready", "progress": 100},
    "llm": {"status": "ready", "progress": 100},
    "embedder": {"status": "permanent_error", "progress": 0, "error": "CUDA out of memory"},
    "dspy_lm": {"status": "ready", "progress": 100},
}

_MIXED_STATUSES = {
    "cross_encoder": {"status": "ready", "progress": 100},
    "llm": {"status": "loading", "progress": 70, "message": "Loading..."},
    "embedder": {"status": "ready", "progress": 100},
    "dspy_lm": {"status": "error", "progress": 50, "message": "Retrying..."},
}

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockSessionState:
    """A dict-like object that also supports attribute read/write.

    ``streamlit.session_state`` uses both ``st.session_state.foo = bar``
    (attribute access) and ``st.session_state.get("foo", default)`` (dict
    method).  This mock supports both styles transparently.
    """

    def __init__(self, initial=None):
        object.__setattr__(self, "_data", {})
        if initial:
            for k, v in initial.items():
                self[k] = v

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self._data[name] = value

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __contains__(self, key):
        return key in self._data

    def __repr__(self):
        return f"MockSessionState({self._data!r})"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_streamlit():
    """Replace ``streamlit`` module with mocks for every test.

    Provides:
    - ``st.session_state`` — a ``MockSessionState`` (no keys set by default)
    - ``st.empty()`` — returns a ``MagicMock`` (supports context-manager)
    - ``st.rerun()`` — no-op
    - ``st.markdown``, ``st.progress``, ``st.caption``, ``st.error``,
      ``st.success`` — no-ops
    """
    with patch("client.components.model_status.st") as mock_st:
        mock_st.session_state = MockSessionState()
        mock_st.empty.return_value = MagicMock()
        mock_st.rerun = MagicMock()
        mock_st.markdown = MagicMock()
        mock_st.progress = MagicMock()
        mock_st.caption = MagicMock()
        mock_st.error = MagicMock()
        mock_st.success = MagicMock()
        yield mock_st


@pytest.fixture(autouse=True)
def mock_time_sleep():
    """Prevent ``time.sleep`` from actually pausing during tests."""
    with patch("client.components.model_status.time.sleep") as mock_sleep:
        yield mock_sleep


# ---------------------------------------------------------------------------
# 16.1 — Early-exit paths
# ---------------------------------------------------------------------------


class TestEarlyExit:
    """Both early-exit paths return immediately without making an HTTP call."""

    def test_early_exit_when_models_ready(self, mock_streamlit, mock_time_sleep):
        """When ``st.session_state.models_ready`` is ``True``, the function
        returns ``all_ready=True`` immediately."""
        mock_streamlit.session_state.models_ready = True

        with patch("client.components.model_status.requests.get") as mock_get:
            result = model_status_banner("http://localhost:8000/api/v1", {})

        assert result["all_ready"] is True
        assert result["embedder_ready"] is True
        assert result["llm_ready"] is True
        assert result["cross_encoder_ready"] is True
        assert result["dspy_lm_ready"] is True
        # No HTTP call should be made
        mock_get.assert_not_called()
        # rerun should not be called
        mock_streamlit.rerun.assert_not_called()

    def test_early_exit_when_permanent_error(self, mock_streamlit, mock_time_sleep):
        """When ``st.session_state.models_permanent_error`` is ``True``, the
        function returns ``all_ready=False`` immediately using cached data."""
        mock_streamlit.session_state.models_permanent_error = True
        mock_streamlit.session_state.models_data = _EMBEDDER_PERMANENT_ERROR

        with patch("client.components.model_status.requests.get") as mock_get:
            result = model_status_banner("http://localhost:8000/api/v1", {})

        assert result["all_ready"] is False
        assert result["embedder_ready"] is False
        # Other models were ready
        assert result["llm_ready"] is True
        assert result["cross_encoder_ready"] is True
        assert result["dspy_lm_ready"] is True
        mock_get.assert_not_called()
        mock_streamlit.rerun.assert_not_called()

    def test_early_exit_permanent_error_with_no_cached_data(
        self, mock_streamlit, mock_time_sleep
    ):
        """When permanent_error is set but no ``models_data`` is cached,
        the fallback returns ``embedder_ready=False`` (unknown → not ready)."""
        mock_streamlit.session_state.models_permanent_error = True
        # Do NOT set models_data — should fall back to _default_models

        with patch("client.components.model_status.requests.get") as mock_get:
            result = model_status_banner("http://localhost:8000/api/v1", {})

        assert result["all_ready"] is False
        assert result["embedder_ready"] is False
        assert result["llm_ready"] is False  # unknown → not ready
        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# 16.1 — HTTP 200 with all models ready
# ---------------------------------------------------------------------------


class TestHttp200AllReady:
    """When the health endpoint reports all models as ``ready``."""

    def test_returns_all_ready_true(self, mock_streamlit, mock_time_sleep):
        """``all_ready`` is ``True``, all per-model flags are ``True``,
        and the success banner is rendered."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _ALL_READY
            mock_get.return_value = mock_response

            result = model_status_banner("http://localhost:8000/api/v1", {})

        assert result["all_ready"] is True
        assert result["embedder_ready"] is True
        assert result["llm_ready"] is True
        assert result["cross_encoder_ready"] is True
        assert result["dspy_lm_ready"] is True
        assert result["models_data"] == _ALL_READY

    def test_caches_ready_state(self, mock_streamlit, mock_time_sleep):
        """``st.session_state.models_ready`` is set to ``True`` after a
        successful all-ready response."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _ALL_READY
            mock_get.return_value = mock_response

            model_status_banner("http://localhost:8000/api/v1", {})

        assert mock_streamlit.session_state.models_ready is True

    def test_clears_placeholder_when_ready(self, mock_streamlit, mock_time_sleep):
        """The ``st.empty()`` placeholder is cleared when all models are ready."""
        mock_placeholder = MagicMock()
        mock_streamlit.empty.return_value = mock_placeholder

        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _ALL_READY
            mock_get.return_value = mock_response

            model_status_banner("http://localhost:8000/api/v1", {})

        mock_placeholder.empty.assert_called_once()


# ---------------------------------------------------------------------------
# 16.1 — HTTP 200 with embedder loading
# ---------------------------------------------------------------------------


class TestHttp200EmbedderLoading:
    """When the health endpoint shows the embedder is still loading."""

    def test_returns_all_ready_false(self, mock_streamlit, mock_time_sleep):
        """``all_ready`` is ``False`` and ``embedder_ready`` is ``False``."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _EMBEDDER_LOADING
            mock_get.return_value = mock_response

            result = model_status_banner("http://localhost:8000/api/v1", {})

        assert result["all_ready"] is False
        assert result["embedder_ready"] is False
        # Other models that are ready should still show ready
        assert result["llm_ready"] is True
        assert result["cross_encoder_ready"] is True

    def test_calls_rerun_and_sleep(self, mock_streamlit, mock_time_sleep):
        """When any model is still loading, the function calls ``time.sleep``
        and ``st.rerun()`` before falling through."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _EMBEDDER_LOADING
            mock_get.return_value = mock_response

            model_status_banner("http://localhost:8000/api/v1", {})

        mock_time_sleep.assert_called_once_with(0.2)
        mock_streamlit.rerun.assert_called_once()

    def test_session_state_not_marked_ready(self, mock_streamlit, mock_time_sleep):
        """``models_ready`` remains ``False`` when models are still loading."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _EMBEDDER_LOADING
            mock_get.return_value = mock_response

            model_status_banner("http://localhost:8000/api/v1", {})

        # models_ready may not be in session state at all (not set by function)
        # or may be False — either is acceptable
        ready = mock_streamlit.session_state.get("models_ready", False)
        assert ready is False

    def test_caches_models_data(self, mock_streamlit, mock_time_sleep):
        """``models_data`` is saved to session state even when not all ready."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _EMBEDDER_LOADING
            mock_get.return_value = mock_response

            model_status_banner("http://localhost:8000/api/v1", {})

        assert mock_streamlit.session_state.models_data == _EMBEDDER_LOADING


# ---------------------------------------------------------------------------
# 16.1 — HTTP 200 with permanent error
# ---------------------------------------------------------------------------


class TestHttp200PermanentError:
    """When the health endpoint reports a permanent error for a model."""

    def test_returns_all_ready_false(self, mock_streamlit, mock_time_sleep):
        """``all_ready`` is ``False``, the errored model's flag is ``False``."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _EMBEDDER_PERMANENT_ERROR
            mock_get.return_value = mock_response

            result = model_status_banner("http://localhost:8000/api/v1", {})

        assert result["all_ready"] is False
        assert result["embedder_ready"] is False
        assert result["llm_ready"] is True

    def test_sets_permanent_error_in_session_state(
        self, mock_streamlit, mock_time_sleep
    ):
        """``models_permanent_error`` is set in session state."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _EMBEDDER_PERMANENT_ERROR
            mock_get.return_value = mock_response

            model_status_banner("http://localhost:8000/api/v1", {})

        assert mock_streamlit.session_state.models_permanent_error is True

    def test_calls_rerun_and_sleep(self, mock_streamlit, mock_time_sleep):
        """``st.rerun()`` and ``time.sleep(0.2)`` are called when a permanent
        error is present (because ``all_ready`` is ``False`` and the function
        enters the sleep/rerun branch before the fallback)."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _EMBEDDER_PERMANENT_ERROR
            mock_get.return_value = mock_response

            model_status_banner("http://localhost:8000/api/v1", {})

        mock_time_sleep.assert_called_once_with(0.2)
        mock_streamlit.rerun.assert_called_once()


# ---------------------------------------------------------------------------
# 16.1 — HTTP 200 with mixed statuses
# ---------------------------------------------------------------------------


class TestHttp200MixedStatuses:
    """When models report a mix of ready, loading, and error statuses."""

    def test_per_model_flags_reflect_status(self, mock_streamlit, mock_time_sleep):
        """Each per-model ``*_ready`` flag correctly reflects that model's
        status in the response."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _MIXED_STATUSES
            mock_get.return_value = mock_response

            result = model_status_banner("http://localhost:8000/api/v1", {})

        # cross_encoder is ready → True
        assert result["cross_encoder_ready"] is True
        # llm is loading → False
        assert result["llm_ready"] is False
        # embedder is ready → True
        assert result["embedder_ready"] is True
        # dspy_lm is error → False
        assert result["dspy_lm_ready"] is False
        assert result["all_ready"] is False

    def test_embedder_ready_true_when_embedder_is_ready(
        self, mock_streamlit, mock_time_sleep
    ):
        """``embedder_ready`` is ``True`` when the embedder reports ``ready``
        even if other models are not ready (16.3)."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _MIXED_STATUSES
            mock_get.return_value = mock_response

            result = model_status_banner("http://localhost:8000/api/v1", {})

        # In MIXED_STATUSES, embedder is "ready", llm is "loading"
        assert result["embedder_ready"] is True
        assert result["llm_ready"] is False


# ---------------------------------------------------------------------------
# 16.1 — Embedder-ready flag (16.3)
# ---------------------------------------------------------------------------


class TestEmbedderReadyFlag:
    """Verifies that ``embedder_ready`` return value correctly reflects the
    embedder's readiness from the backend response (Task 16.3)."""

    def test_embedder_ready_true(self, mock_streamlit, mock_time_sleep):
        """When embedder status is ``ready``, ``embedder_ready`` is ``True``."""
        models = dict(_ALL_READY)
        models["embedder"] = {"status": "ready", "progress": 100, "message": "Ready"}

        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = models
            mock_get.return_value = mock_response

            result = model_status_banner("http://localhost:8000/api/v1", {})
        assert result["embedder_ready"] is True

    def test_embedder_ready_false_loading(self, mock_streamlit, mock_time_sleep):
        """When embedder status is ``loading``, ``embedder_ready`` is ``False``."""
        models = dict(_ALL_READY)
        models["embedder"] = {"status": "loading", "progress": 50}

        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = models
            mock_get.return_value = mock_response

            result = model_status_banner("http://localhost:8000/api/v1", {})
        assert result["embedder_ready"] is False

    def test_embedder_ready_false_error(self, mock_streamlit, mock_time_sleep):
        """When embedder status is ``error``, ``embedder_ready`` is ``False``."""
        models = dict(_ALL_READY)
        models["embedder"] = {"status": "error", "progress": 0, "message": "OOM"}

        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = models
            mock_get.return_value = mock_response

            result = model_status_banner("http://localhost:8000/api/v1", {})
        assert result["embedder_ready"] is False

    def test_embedder_ready_false_permanent_error(
        self, mock_streamlit, mock_time_sleep
    ):
        """When embedder status is ``permanent_error``, ``embedder_ready``
        is ``False``."""
        models = dict(_ALL_READY)
        models["embedder"] = {
            "status": "permanent_error",
            "progress": 0,
            "error": "GPU error",
        }

        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = models
            mock_get.return_value = mock_response

            result = model_status_banner("http://localhost:8000/api/v1", {})
        assert result["embedder_ready"] is False

    def test_embedder_ready_false_unknown(self, mock_streamlit, mock_time_sleep):
        """When embedder status is unknown/missing, ``embedder_ready``
        is ``False``."""
        models = dict(_ALL_READY)
        models["embedder"] = {"status": "unknown"}

        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = models
            mock_get.return_value = mock_response

            result = model_status_banner("http://localhost:8000/api/v1", {})
        assert result["embedder_ready"] is False


# ---------------------------------------------------------------------------
# 16.1 — HTTP request failure
# ---------------------------------------------------------------------------


class TestRequestException:
    """When ``requests.get`` raises a ``RequestException``."""

    def test_calls_rerun_and_sleep(self, mock_streamlit, mock_time_sleep):
        """On ``RequestException``, the function calls ``time.sleep(0.2)``
        and ``st.rerun()`` before falling through."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_get.side_effect = (
                __import__("requests").RequestException("Connection refused")
            )

            model_status_banner("http://localhost:8000/api/v1", {})

        mock_time_sleep.assert_called_once_with(0.2)
        mock_streamlit.rerun.assert_called_once()

    def test_returns_fallback_all_ready_false(
        self, mock_streamlit, mock_time_sleep
    ):
        """After a ``RequestException``, the fallback return has
        ``all_ready=False``."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_get.side_effect = (
                __import__("requests").RequestException("Connection refused")
            )

            result = model_status_banner("http://localhost:8000/api/v1", {})

        assert result["all_ready"] is False
        # All per-model flags should be False since there's no cached data
        assert result["embedder_ready"] is False
        assert result["llm_ready"] is False
        assert result["cross_encoder_ready"] is False
        assert result["dspy_lm_ready"] is False

    def test_rerun_called_after_exception(self, mock_streamlit, mock_time_sleep):
        """Exactly one ``st.rerun()`` call is made after a network error."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_get.side_effect = (
                __import__("requests").RequestException("Timeout")
            )

            model_status_banner("http://localhost:8000/api/v1", {})

        assert mock_streamlit.rerun.call_count == 1


# ---------------------------------------------------------------------------
# 16.1 — Session state initialization
# ---------------------------------------------------------------------------


class TestSessionStateInitialization:
    """On first call, the function initializes missing session state keys."""

    def test_initializes_models_ready(self, mock_streamlit, mock_time_sleep):
        """``models_ready`` is initialized to ``False`` if not present."""
        # Ensure key does not exist
        assert "models_ready" not in mock_streamlit.session_state

        with patch("client.components.model_status.requests.get") as mock_get:
            mock_get.side_effect = (
                __import__("requests").RequestException("Connection refused")
            )
            model_status_banner("http://localhost:8000/api/v1", {})

        assert mock_streamlit.session_state.models_ready is False

    def test_initializes_models_permanent_error(self, mock_streamlit, mock_time_sleep):
        """``models_permanent_error`` is initialized to ``False`` if not present."""
        assert "models_permanent_error" not in mock_streamlit.session_state

        with patch("client.components.model_status.requests.get") as mock_get:
            mock_get.side_effect = (
                __import__("requests").RequestException("Connection refused")
            )
            model_status_banner("http://localhost:8000/api/v1", {})

        assert mock_streamlit.session_state.models_permanent_error is False


# ---------------------------------------------------------------------------
# 16.2 — URL verification
# ---------------------------------------------------------------------------


class TestUrlAndHeaders:
    """Verifies the function makes an HTTP GET to the correct endpoint
    (Task 16.2)."""

    def test_makes_request_to_correct_url(self, mock_streamlit, mock_time_sleep):
        """The function calls ``GET {api_base_url}/health/models``."""
        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _ALL_READY
            mock_get.return_value = mock_response

            model_status_banner(
                "http://test:9999/api/v1",
                {"Authorization": "Bearer test-token"},
            )

        mock_get.assert_called_once_with(
            "http://test:9999/api/v1/health/models",
            timeout=2,
            headers={"Authorization": "Bearer test-token"},
        )

    def test_passes_headers_to_request(self, mock_streamlit, mock_time_sleep):
        """Custom headers (e.g. Authorization) are forwarded to the request."""
        custom_headers = {"Authorization": "Bearer abc123", "X-Custom": "value"}

        with patch("client.components.model_status.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _ALL_READY
            mock_get.return_value = mock_response

            model_status_banner("http://localhost:8000/api/v1", custom_headers)

        _, kwargs = mock_get.call_args
        assert kwargs["headers"] == custom_headers
