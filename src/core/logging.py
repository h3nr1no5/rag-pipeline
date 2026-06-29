"""Core logging utilities — log level manager, structured logging helper, filters."""
import logging


class LogLevelManager:
    """Singleton that manages in-memory per-module log level overrides.

    Provides runtime control of logger levels without restart.
    Overrides are stored in a dict[str, int] and reset on restart.
    """
    _instance: "LogLevelManager | None" = None
    _overrides: dict[str, int]

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._overrides = {}
        return cls._instance

    def get_level(self, logger_name: str) -> int | None:
        """Return the override level for *logger_name*, or None if not overridden."""
        return self._overrides.get(logger_name)

    def set_level(self, logger_name: str, level: int | None) -> None:
        """Set or clear a log level override.

        If *level* is None, the override is removed (restoring default).
        Otherwise *logger_name* will use *level* at or above its configured level.
        """
        if level is None:
            self._overrides.pop(logger_name, None)
        else:
            self._overrides[logger_name] = level

    def reset(self) -> None:
        """Clear all overrides."""
        self._overrides.clear()

    def get_all_overrides(self) -> dict[str, int]:
        """Return a shallow copy of all current overrides."""
        return dict(self._overrides)


def log_structured(module_name: str, event_type: str, level: int = logging.INFO, **context) -> None:
    """Emit a single structured log line with event_type and key=value context.

    Format:  <event_type> key1=value1 key2=value2 ...

    Values are escaped: backslash first, then = and spaces to prevent log injection.
    Uses the logger for *module_name* (e.g., "src.domain.services.retrieval").
    """
    logger = logging.getLogger(module_name)

    def _escape(v: object) -> str:
        s = str(v)
        return s.replace("\\", "\\\\").replace("=", "\\=").replace(" ", "\\ ")

    context_str = " ".join(f"{k}={_escape(v)}" for k, v in sorted(context.items()))
    msg = f"{event_type} {context_str}" if context_str else event_type
    logger.log(level, msg)


class ModuleLevelFilter(logging.Filter):
    """Filter that consults LogLevelManager to dynamically override log levels.

    For each log record, checks if the logger name has a level override in
    LogLevelManager. If so, applies the override level to the record.
    This enables the toggle endpoint to dynamically change log verbosity.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        manager = LogLevelManager()
        # Walk up the logger hierarchy to find the best matching override
        name = record.name
        while name:
            override = manager.get_level(name)
            if override is not None:
                # If the override level is higher than the record's level,
                # mark the record as not to be logged
                if override > record.levelno:
                    return False
                break
            # Try parent logger
            dot = name.rfind(".")
            if dot == -1:
                break
            name = name[:dot]
        return True


class DevModeFilter(logging.Filter):
    """Static filter that suppresses noisy framework-level INFO messages.

    Currently suppresses `uvicorn.access` INFO messages unless the
    uvicorn.access logger has been overridden to DEBUG (via LogLevelManager).

    ERROR and CRITICAL messages always pass through.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Never suppress ERROR or CRITICAL
        if record.levelno >= logging.ERROR:
            return True

        # Suppress uvicorn.access INFO unless overridden to DEBUG
        if record.name == "uvicorn.access" and record.levelno == logging.INFO:
            manager = LogLevelManager()
            override = manager.get_level("uvicorn.access")
            if override != logging.DEBUG:
                return False

        return True
