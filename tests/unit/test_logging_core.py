"""Unit tests for core logging utilities — LogLevelManager, DevModeFilter, log_structured."""
import logging

import pytest

from src.core.logging import LogLevelManager


# ---------------------------------------------------------------------------
# 10.1 — LogLevelManager
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_manager():
    """Reset the singleton between tests."""
    LogLevelManager().reset()
    yield


class TestLogLevelManager:
    """Tests for LogLevelManager singleton."""

    def test_default_returns_none(self):
        """Manager returns None for unknown modules."""
        mgr = LogLevelManager()
        assert mgr.get_level("nonexistent.module") is None

    def test_set_and_get_level(self):
        """Setting a level returns it on get."""
        mgr = LogLevelManager()
        mgr.set_level("test.module", logging.DEBUG)
        assert mgr.get_level("test.module") == logging.DEBUG

    def test_set_none_clears_override(self):
        """Setting level to None removes the override."""
        mgr = LogLevelManager()
        mgr.set_level("test.module", logging.DEBUG)
        mgr.set_level("test.module", None)
        assert mgr.get_level("test.module") is None

    def test_reset_clears_all(self):
        """reset() removes all overrides."""
        mgr = LogLevelManager()
        mgr.set_level("mod.a", logging.DEBUG)
        mgr.set_level("mod.b", logging.INFO)
        mgr.reset()
        assert mgr.get_level("mod.a") is None
        assert mgr.get_level("mod.b") is None

    def test_singleton(self):
        """LogLevelManager is a proper singleton."""
        mgr1 = LogLevelManager()
        mgr2 = LogLevelManager()
        mgr1.set_level("test", logging.DEBUG)
        assert mgr2.get_level("test") == logging.DEBUG
        assert mgr1 is mgr2

    def test_get_all_overrides(self):
        """get_all_overrides returns a copy of all overrides."""
        mgr = LogLevelManager()
        mgr.set_level("test", logging.DEBUG)
        overrides = mgr.get_all_overrides()
        assert overrides == {"test": logging.DEBUG}
        # Verify it's a copy
        overrides.clear()
        assert mgr.get_level("test") == logging.DEBUG


# ---------------------------------------------------------------------------
# 10.2 — DevModeFilter
# ---------------------------------------------------------------------------

class TestDevModeFilter:
    """Tests for DevModeFilter."""

    def _make_record(self, name, levelno, msg="test"):
        """Helper to create a LogRecord."""
        return logging.LogRecord(name, levelno, "", 0, msg, (), None)

    def test_suppresses_uvicorn_access_info(self):
        """DevModeFilter suppresses uvicorn.access INFO messages."""
        from src.core.logging import DevModeFilter
        LogLevelManager().reset()
        f = DevModeFilter()
        record = self._make_record("uvicorn.access", logging.INFO)
        assert f.filter(record) is False

    def test_passes_uvicorn_access_error(self):
        """DevModeFilter does NOT suppress ERROR from uvicorn.access."""
        from src.core.logging import DevModeFilter
        LogLevelManager().reset()
        f = DevModeFilter()
        record = self._make_record("uvicorn.access", logging.ERROR)
        assert f.filter(record) is True

    def test_passes_uvicorn_access_debug_when_overridden(self):
        """DevModeFilter allows uvicorn.access INFO when user overrides to DEBUG."""
        from src.core.logging import DevModeFilter
        LogLevelManager().reset()
        LogLevelManager().set_level("uvicorn.access", logging.DEBUG)
        f = DevModeFilter()
        record = self._make_record("uvicorn.access", logging.INFO)
        assert f.filter(record) is True

    def test_passes_non_uvicorn_info(self):
        """DevModeFilter passes non-uvicorn INFO messages."""
        from src.core.logging import DevModeFilter
        f = DevModeFilter()
        record = self._make_record("my.module", logging.INFO)
        assert f.filter(record) is True

    def test_passes_critical(self):
        """DevModeFilter passes CRITICAL messages."""
        from src.core.logging import DevModeFilter
        f = DevModeFilter()
        record = self._make_record("uvicorn.access", logging.CRITICAL)
        assert f.filter(record) is True


# ---------------------------------------------------------------------------
# 10.3 — log_structured
# ---------------------------------------------------------------------------

class TestLogStructured:
    """Tests for log_structured helper."""

    def test_emits_structured_format(self, caplog):
        """log_structured emits event_type key=value ... format."""
        from src.core.logging import log_structured
        caplog.set_level(logging.INFO)
        log_structured("test.module", "test_event", user_id="u1", count=5, active=True)
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.name == "test.module"
        assert record.levelno == logging.INFO
        msg = record.getMessage()
        assert "test_event" in msg
        assert "user_id=u1" in msg
        assert "count=5" in msg
        assert "active=True" in msg

    def test_uses_custom_level(self, caplog):
        """log_structured respects the level parameter."""
        from src.core.logging import log_structured
        caplog.set_level(logging.DEBUG)
        log_structured("test.module", "debug_event", level=logging.DEBUG, detail="test")
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.DEBUG

    def test_no_context_still_emits_event(self, caplog):
        """log_structured works with only event_type."""
        from src.core.logging import log_structured
        caplog.set_level(logging.INFO)
        log_structured("test.module", "bare_event")
        assert len(caplog.records) == 1
        assert caplog.records[0].getMessage() == "bare_event"
