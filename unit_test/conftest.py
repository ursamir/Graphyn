# unit_test/conftest.py
"""Shared fixtures for the unit_test suite."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.core.nodes.registry import NodeRegistry
from app.models.audio_sample import AudioSample


# ── Registry isolation ────────────────────────────────────────────────────────

@pytest.fixture
def fresh_registry() -> NodeRegistry:
    """Return a new, empty NodeRegistry for each test.

    Prevents node registrations in one test from contaminating another.
    """
    return NodeRegistry()


# ── Plugin install target ─────────────────────────────────────────────────────

@pytest.fixture
def tmp_plugin_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for plugin installation.

    The real plugins/ directory is NEVER touched by any test.
    """
    d = tmp_path / "plugins"
    d.mkdir()
    return d


# ── AudioSample factory ───────────────────────────────────────────────────────

@pytest.fixture
def make_audio_sample():
    """Factory fixture: make_audio_sample(sr=16000, n=1600, label='test') -> AudioSample."""
    def _factory(
        sr: int = 16000,
        n: int = 1600,
        label: str = "test",
        path: str = "/fake/audio.wav",
    ) -> AudioSample:
        rng = np.random.default_rng(42)
        data = rng.standard_normal(n).astype(np.float32)
        return AudioSample(path=path, sample_rate=sr, data=data, label=label)
    return _factory


# ── Thread safety — prevent hangs ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_threads():
    """Patch ThreadPoolExecutor.submit and Thread.start to no-ops.

    Applied to every test automatically. Prevents background threads from
    keeping the process alive after a test completes.
    """
    noop = MagicMock(return_value=None)
    with (
        patch("concurrent.futures.ThreadPoolExecutor.submit", noop),
        patch("threading.Thread.start", noop),
    ):
        yield


# ── REST API client ───────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    """Return a synchronous FastAPI TestClient."""
    from fastapi.testclient import TestClient
    from app.api.main import app
    return TestClient(app, raise_server_exceptions=True)


# ── Isolated workspace ────────────────────────────────────────────────────────

@pytest.fixture
def tmp_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated workspace directory and point GRAPHYN_PROJECT_DIR at it.

    Use this fixture in tests that read/write workspace files (runs, cache, etc.)
    to avoid polluting the real workspace.
    """
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    return ws


# ── Minimal node helpers (used by registry/discovery tests) ──────────────────

@pytest.fixture
def minimal_node_cls():
    """Return a minimal valid Node subclass for registry tests."""
    from typing import ClassVar
    from app.core.nodes.base import Node
    from app.core.nodes.config import NodeConfig
    from app.core.nodes.metadata import NodeMetadata
    from app.core.nodes.ports import InputPort, OutputPort

    class _MinimalNode(Node):
        node_type: ClassVar[str] = "_minimal_test_node"
        input_ports: ClassVar[dict] = {
            "input": InputPort(name="input", data_type=list)
        }
        output_ports: ClassVar[dict] = {
            "output": OutputPort(name="output", data_type=list)
        }
        metadata: ClassVar[NodeMetadata] = NodeMetadata(
            node_type="_minimal_test_node",
            label="Minimal",
            description="Minimal test node.",
            category="Test",
        )

        class Config(NodeConfig):
            pass

        def process(self, data):
            return data

    return _MinimalNode


@pytest.fixture
def minimal_meta():
    """Return a minimal NodeMetadata for registry tests."""
    from app.core.nodes.metadata import NodeMetadata
    return NodeMetadata(
        node_type="_minimal_test_node",
        label="Minimal",
        description="Minimal test node.",
        category="Test",
    )
