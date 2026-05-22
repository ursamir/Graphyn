# unit_test/api/conftest.py
"""API-specific conftest.

Overrides the global `patch_threads` autouse fixture so that FastAPI's
TestClient can start its internal threads normally.  The global fixture
patches `threading.Thread.start` to a no-op, which prevents TestClient
from ever receiving responses.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def patch_threads():
    """Override the global patch_threads fixture for API tests.

    TestClient requires real threads to function; patching Thread.start
    causes it to hang indefinitely.  This override is a no-op so that
    the TestClient works correctly in all API router tests.
    """
    yield
