"""Regression test: dspy.configure() must NOT be called during startup lifespan.

After the fix (removing the lifespan fallback from ``main.py``), the only
legitimate call site for ``dspy.configure()`` is inside ``warmup_models()``.
This test ensures that if someone ever re-adds a ``dspy.configure()`` call to
the lifespan task, the regression is caught immediately.

Why existing tests missed the async task affinity bug
------------------------------------------------------
- ``test_api_docs_e2e.py`` mocks ``warmup_models()`` (to avoid native model
  segfaults in pytest), which means the second ``dspy.configure()`` call
  from the warmup task never fires.
- Unit tests for ``WarmupState`` test the state machine directly and never
  trigger the startup sequence.
- The bug only manifests when **both** call sites execute from different
  ``asyncio.Task`` objects, which only happens in production (or a test that
  runs the real ``warmup_models()`` alongside the lifespan).
- ``httpx.ASGITransport`` in v0.28+ does **not** trigger ASGI lifespan
  events automatically, so simply making an HTTP request is insufficient.
  This test manually enters the lifespan context manager.

More generally: the test gap exists because mocking ``warmup_models()`` is
necessary for test stability, but it also suppresses the race condition.
This regression test closes the gap by verifying the **contract** — the
lifespan must never call ``dspy.configure()`` — rather than reproducing the
race dynamically. If the contract is violated, this test fails regardless
of whether the race is triggered.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ── Module-level patches (must precede any src imports) ───────────────────

# Prevent background model warmup from loading native models (segfault guard).
patch("src.domain.services.warmup.warmup_models", new_callable=AsyncMock).start()

# Prevent get_mlx_dspy_lm from loading MLX (Metal GPU) during the lifespan,
# which would conflict with PyTorch MPS and cause segfaults.
patch(
    "src.domain.rag.api_docs.pipeline.lm_adapter.get_mlx_dspy_lm",
    return_value=MagicMock(),
).start()

# Install a sentinel mock on dspy.configure *before* main.py imports dspy,
# so the test can assert whether configure was called during lifespan startup.
_dspy_configure = MagicMock()
patch("dspy.configure", _dspy_configure).start()


@pytest.mark.asyncio
async def test_no_dspy_configure_during_lifespan(setup_test_db):
    """After the fix, dspy.configure() must NOT be invoked during startup.

    The lifespan may launch ``warmup_models()`` as a background task, but it
    must **not** call ``dspy.configure()`` itself.  Violating this constraint
    recreates the async task affinity ``RuntimeError`` that this change fixes.

    If this test fails, someone likely re-added a ``dspy.configure()`` call
    to the lifespan — revert it.
    """
    # Import the lifespan function explicitly — httpx 0.28+ does NOT
    # trigger ASGI lifespan events via ASGITransport, so we must enter
    # the context manager manually.
    from src.api.main import app, lifespan

    # Enter the lifespan (startup runs here), make a request to confirm
    # the app is functional, then exit (shutdown runs here).
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/health")
            assert resp.status_code == 200, f"Health check failed: {resp.text}"

    # dspy.configure must NOT have been called during startup
    _dspy_configure.assert_not_called()
