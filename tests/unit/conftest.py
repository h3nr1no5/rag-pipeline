"""No-op fixture overrides for unit tests.

These override the autouse fixtures in tests/conftest.py so that unit tests
do not set up a database, clean uploads, or cancel background tasks.
"""

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    """Override: skip database setup/teardown for unit tests."""
    yield


@pytest.fixture(scope="function", autouse=True)
def clean_uploads_dir():
    """Override: skip uploads directory cleanup for unit tests."""
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def cancel_background_tasks():
    """Override: skip background task cancellation for unit tests."""
    yield
