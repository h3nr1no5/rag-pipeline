"""Frontend E2E test fixtures.

Starts real backend (FastAPI / uvicorn) and frontend (Streamlit) server
subprocesses for Playwright-based end-to-end tests.

All fixtures in this module are synchronous (``subprocess.Popen``) -- no
``asyncio`` is used.  Session-scoped fixtures start ONCE per test run for
performance.
"""

import atexit
import os
import socket
import subprocess
import time
import uuid

import pytest
import requests

# Import the pytest-playwright plugin module so that its fixtures (browser,
# context, page, etc.) are discoverable by pytest.  The session-scoped
# ``browser`` fixture (launches headless Chromium) is used by our custom
# ``page`` fixture below.
from pytest_playwright import pytest_playwright as _pw_plugin  # noqa: F401

pytestmark = pytest.mark.slow

# Override the root-level async ``cancel_background_tasks`` fixture (which is
# ``autouse=True`` in ``tests/conftest.py``).  The root-level fixture is async
# and conflicts with synchronous Playwright tests that don't use
# pytest-asyncio's event loop.  This synchronous no-op replaces it.
@pytest.fixture(scope="function", autouse=True)
def cancel_background_tasks():
    yield


# Override the root-level async ``setup_test_db`` fixture (which is
# ``autouse=True`` in ``tests/conftest.py``).  The E2E tests use a real
# backend subprocess with its own isolated database, so the per-test
# monkeypatching is unwanted.  This synchronous no-op also unsets
# ``TEST_DATABASE_URL`` from the parent environment so the backend
# subprocess doesn't inherit it as a fallback (``DATABASE_URL`` is set
# explicitly in the ``backend_server`` fixture).
@pytest.fixture(scope="function", autouse=True)
def setup_test_db():
    os.environ.pop("TEST_DATABASE_URL", None)
    yield


# ---------------------------------------------------------------------------
# Global state for atexit fallback cleanup
# ---------------------------------------------------------------------------
_subprocesses: list[subprocess.Popen] = []
_db_paths: list[str] = []


def _cleanup_all() -> None:
    """Kill all tracked subprocesses and remove tracked DB files.

    This is registered via ``atexit`` as a safety net in case the pytest
    session is interrupted (e.g. KeyboardInterrupt) before fixture teardown
    runs.  It is safe to call even after normal teardown because:
    * ``_kill_process`` checks ``proc.poll()`` before signalling.
    * ``_remove_sqlite_file`` catches ``Exception`` for missing files.
    """
    for proc in list(_subprocesses):
        _kill_process(proc)
    for db_path in list(_db_paths):
        _remove_sqlite_file(db_path)


atexit.register(_cleanup_all)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _remove_sqlite_file(db_path: str) -> None:
    """Remove a SQLite database file along with any WAL/SHM journal files."""
    for path in (db_path, db_path + "-wal", db_path + "-shm"):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _find_free_port() -> int:
    """Return a random available TCP port on ``127.0.0.1``.

    Uses the socket-bind-to-port-0 trick.  There is a small TOCTOU race
    between closing the socket and starting the server, but it is vanishingly
    unlikely in CI / single-machine test environments.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _wait_for_http_ok(
    url: str,
    timeout: float = 30.0,
    interval: float = 0.5,
    content_check: str | None = None,
) -> bool:
    """Poll *url* until it returns HTTP 200 (optionally with *content_check*).

    Parameters
    ----------
    url:
        The URL to poll.
    timeout:
        Maximum seconds to keep polling (default 30).
    interval:
        Seconds between polls (default 0.5).
    content_check:
        If provided, the response text must contain this substring before the
        check succeeds (default ``None`` -- any HTTP 200 is sufficient).

    Returns
    -------
    bool
        ``True`` if the server responded with 200 (and optionally matched
        *content_check*) within *timeout*, ``False`` otherwise.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                if content_check is None or content_check in resp.text:
                    return True
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(interval)
    return False


def _kill_process(proc: subprocess.Popen) -> None:
    """Send SIGTERM to *proc*, wait 10 s, then SIGKILL if still alive.

    Safe to call multiple times -- if the process has already exited,
    ``proc.poll()`` returns a non-``None`` value and this is a no-op.
    """
    if proc.poll() is not None:
        return
    try:
        proc.terminate()  # SIGTERM
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()  # SIGKILL
            proc.wait(timeout=5)
        except Exception:
            pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def backend_server():
    """Start the FastAPI backend as a real HTTP server subprocess.

    Returns a dict with keys:
        ``port``     -- TCP port the server is listening on
        ``base_url`` -- ``http://127.0.0.1:{port}``
        ``db_path``  -- absolute path to the isolated SQLite database

    The server uses a unique, isolated SQLite database created in ``./data/``.
    Real LLM, embedder, and DSPy models are loaded if the environment
    supports them.
    """
    port = _find_free_port()
    db_path = os.path.abspath(f"./data/test_e2e_{uuid.uuid4().hex[:12]}.sqlite")
    base_url = f"http://127.0.0.1:{port}"

    os.makedirs("./data", exist_ok=True)

    # Build environment for the subprocess.
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    # Force INFO-level logging to prevent the subprocess from hanging due to
    # a full stderr pipe buffer.  DEBUG-level logs from httpx / huggingface_hub
    # (thousands of ``connect_tcp.started`` lines during CrossEncoder model
    # loading) can fill the OS pipe buffer (~64 KB on macOS), causing the
    # subprocess's ``write()`` to block and the health check to time out.
    env["LOG_LEVEL"] = "INFO"

    # Do NOT set HF_HUB_OFFLINE -- use whatever the parent env has.

    # Do NOT set TEST_DATABASE_URL -- this is real, not test-double mode.
    # Do NOT set API_DOCS_DSPY_ENABLED -- let it use real DSPy if configured.

    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "src.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _subprocesses.append(proc)
    _db_paths.append(db_path)

    # Health check: this endpoint requires NO authentication and does NOT
    # trigger model lazy-loading (it only reads chunking strategies from DB).
    health_url = f"{base_url}/api/v1/strategies/types"
    if not _wait_for_http_ok(health_url, timeout=30.0, interval=0.5):
        stdout, stderr = proc.communicate(timeout=5)
        _kill_process(proc)
        _remove_sqlite_file(db_path)
        raise RuntimeError(
            f"Backend server failed to start within 30s on port {port}.\n"
            f"stdout:\n{stdout.decode(errors='replace')[:2000]}\n"
            f"stderr:\n{stderr.decode(errors='replace')[:2000]}"
        )

    yield {"port": port, "base_url": base_url, "db_path": db_path}

    # ── Teardown ────────────────────────────────────────────────────────
    _kill_process(proc)
    _remove_sqlite_file(db_path)


@pytest.fixture(scope="session")
def frontend_server(backend_server):
    """Start the Streamlit frontend as a subprocess.

    Depends on ``backend_server`` to set ``API_BASE_URL`` so the frontend
    talks to the isolated backend instance.

    Yields the frontend URL (e.g. ``http://127.0.0.1:PORT``).
    """
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    os.makedirs("./data", exist_ok=True)

    env = os.environ.copy()
    env["API_BASE_URL"] = f"{backend_server['base_url']}/api/v1"

    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "streamlit",
            "run",
            "client/app.py",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
            "--server.enableCORS",
            "false",
            "--server.enableXsrfProtection",
            "false",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _subprocesses.append(proc)

    # Wait for Streamlit to be ready.  We just check that the HTTP server
    # responds (the app content is loaded via WebSocket after the browser connects).
    if not _wait_for_http_ok(
        url, timeout=30.0, interval=0.5
    ):
        stdout, stderr = proc.communicate(timeout=5)
        _kill_process(proc)
        raise RuntimeError(
            f"Frontend server failed to start within 30s on port {port}.\n"
            f"stdout:\n{stdout.decode(errors='replace')[:2000]}\n"
            f"stderr:\n{stderr.decode(errors='replace')[:2000]}"
        )

    yield url

    # ── Teardown ────────────────────────────────────────────────────────
    _kill_process(proc)


# ---------------------------------------------------------------------------
# Function-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def page(browser):
    """Isolated Playwright page for a single test function.

    Uses the session-scoped ``browser`` fixture from ``pytest-playwright``
    (which launches a headless Chromium instance).  This fixture creates
    a fresh browser context for every test, ensuring isolated cookies,
    localStorage, and session state.

    Yields a :class:`playwright.sync_api.Page` ready for interaction.
    """
    context = browser.new_context()
    page_obj = context.new_page()
    yield page_obj
    context.close()
