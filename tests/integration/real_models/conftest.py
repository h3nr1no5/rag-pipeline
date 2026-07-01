"""Conftest for real-model integration tests.

Overrides *seed_singletons* to a no-op so that real ML model singletons
(LLM, embedder, cross-encoder) are retained for end-to-end profiling tests.
"""


import pytest

# ---------------------------------------------------------------------------
# Fixture overrides
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def seed_singletons():
    """No-op override — keep real ML model singletons for profiling."""
    pass  # pragma: no cover


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


