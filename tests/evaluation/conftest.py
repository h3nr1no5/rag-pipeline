"""No-op fixture overrides for evaluation tests.

These override the autouse fixtures in tests/conftest.py so that evaluation
tests do not set up a database, clean uploads, or cancel background tasks.
"""

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    """Override: skip database setup/teardown for evaluation tests."""
    yield


@pytest.fixture(scope="function", autouse=True)
def clean_uploads_dir():
    """Override: skip uploads directory cleanup for evaluation tests."""
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def cancel_background_tasks():
    """Override: skip background task cancellation for evaluation tests."""
    yield
