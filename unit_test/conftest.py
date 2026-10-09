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


# ── Environment isolation (runs before any fixture / plugin load) ────────────
#
# Without this, tests write the developer's real ``~/.graphyn`` (plugin
# registry, credentials store, notifications.jsonl) and the repo ``workspace/``
# which causes cross-run ``PluginAlreadyInstalledError`` cascades and leaks
# test data into the real install. ``pytest_configure`` runs before test
# modules are imported and before the session plugin bootstrap, so every
# ``graphyn_home()`` / ``project_dir()`` lookup resolves into a throwaway dir.

_TEST_ENV_ROOT: Path | None = None
_REAL_HOME_ENV_KEYS = (
    "GRAPHYN_HOME",
    "GRAPHYN_PLUGINS_DIR",
    "GRAPHYN_PLUGIN_VENVS_DIR",
    "GRAPHYN_NOTIFICATIONS_PATH",
    "GRAPHYN_PROJECT_DIR",
    "GRAPHYN_BACKEND",
    "GRAPHYN_CONTROL_URL",
    "GRAPHYN_API_URL",
)


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _real_venvs_dir() -> Path:
    raw = os.environ.get("GRAPHYN_PLUGIN_VENVS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    home = os.environ.get("GRAPHYN_HOME", "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".graphyn"
    return base / "plugins" / "venvs"


def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001
    global _TEST_ENV_ROOT
    import tempfile

    if _TEST_ENV_ROOT is not None:
        return
    real_venvs = _real_venvs_dir()
    for key in _REAL_HOME_ENV_KEYS:
        os.environ.pop(key, None)

    root = Path(tempfile.mkdtemp(prefix="graphyn-pytest-"))
    _TEST_ENV_ROOT = root
    home = root / "graphyn_home"
    venvs = home / "plugins" / "venvs"
    venvs.mkdir(parents=True)
    workspace = root / "workspace"
    workspace.mkdir()

    # Isolated plugin venvs are multi-GB and take many minutes to build, so the
    # developer's existing venvs are *reused* through per-venv symlinks.
    # ``shutil.rmtree(<symlink>, ignore_errors=True)`` (uninstall / gc paths)
    # refuses to follow symlinks, so tests can never delete the real venvs.
    # Missing venvs are never built (see ``_install_offline_venv_guard``).
    if os.environ.get("GRAPHYN_TEST_FRESH_VENVS", "").strip().lower() not in ("1", "true", "yes"):
        if real_venvs.is_dir():
            for child in real_venvs.iterdir():
                if child.is_dir():
                    try:
                        (venvs / child.name).symlink_to(child.resolve(), target_is_directory=True)
                    except OSError:
                        pass

    os.environ["GRAPHYN_HOME"] = str(home)
    os.environ["GRAPHYN_PROJECT_DIR"] = str(workspace)
    os.environ["GRAPHYN_NOTIFICATIONS_PATH"] = str(home / "notifications.jsonl")
    _install_offline_venv_guard(venvs)


def _install_offline_venv_guard(session_venvs: Path) -> None:
    """Stop the suite from building isolated plugin venvs (see ``_venv_guard``).

    Applied in-process and, via a ``sitecustomize`` shim prepended to
    PYTHONPATH, in CLI/API subprocesses running the host interpreter.
    """
    import sys

    from unit_test import _venv_guard

    _venv_guard.install(session_venvs)
    shim = session_venvs.parent.parent.parent / "pyhook"
    shim.mkdir(exist_ok=True)
    (shim / "sitecustomize.py").write_text(_venv_guard.SITECUSTOMIZE_SRC, encoding="utf-8")
    repo_root = str(Path(__file__).resolve().parents[1])
    parts = [str(shim), repo_root] + [
        p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p
    ]
    os.environ["PYTHONPATH"] = os.pathsep.join(parts)
    os.environ[_venv_guard.ENV_DIR] = str(session_venvs)
    os.environ[_venv_guard.ENV_PREFIX] = sys.prefix


def pytest_unconfigure(config: pytest.Config) -> None:  # noqa: ARG001
    import shutil

    if _TEST_ENV_ROOT is not None and os.environ.get("GRAPHYN_TEST_KEEP_HOME", "") == "":
        shutil.rmtree(_TEST_ENV_ROOT, ignore_errors=True)


# ── Heavy (torch / transformers) tests ────────────────────────────────────────

def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:  # noqa: ARG001
    """Skip ``heavy`` tests unless GRAPHYN_RUN_HEAVY=1; ``requires_plugins`` in skip mode."""
    run_heavy = _truthy_env("GRAPHYN_RUN_HEAVY")
    skip_plugins = _truthy_env("GRAPHYN_SKIP_PLUGIN_LOAD")
    heavy_skip = pytest.mark.skip(
        reason=(
            "heavy torch/transformers test: in-process model loads can segfault "
            "(torch/triton) after other tests; set GRAPHYN_RUN_HEAVY=1 and run the "
            "file on its own"
        )
    )
    plugins_skip = pytest.mark.skip(
        reason="requires the populated plugin registry; unset GRAPHYN_SKIP_PLUGIN_LOAD"
    )
    for item in items:
        if not run_heavy and item.get_closest_marker("heavy") is not None:
            item.add_marker(heavy_skip)
        if skip_plugins and item.get_closest_marker("requires_plugins") is not None:
            item.add_marker(plugins_skip)


# ── Session bootstrap ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _bootstrap_node_registry() -> None:
    """Load plugins into the NodeRegistry singleton once per test session.

    Integration-style tests (validation, API) expect real node types such as
    ``audio_conditioner``. Set ``GRAPHYN_SKIP_PLUGIN_LOAD=1`` to skip.
    """
    if os.environ.get("GRAPHYN_SKIP_PLUGIN_LOAD", "").strip().lower() in (
        "1", "true", "yes",
    ):
        return
    from app.core.nodes import initialize_registry
    initialize_registry()


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

_REAL_THREAD_START = threading.Thread.start  # captured before any test can patch it
_REAL_POOL_SUBMIT = __import__("concurrent.futures").futures.ThreadPoolExecutor.submit


@pytest.fixture
def real_threads():
    """Force real ``Thread.start`` / ``ThreadPoolExecutor.submit`` for one test.

    An empty ``patch_threads`` override is not enough when an earlier test
    leaked a patched ``Thread.start`` — TestClient's portal then never starts.
    """
    from concurrent.futures import ThreadPoolExecutor

    saved = (threading.Thread.start, ThreadPoolExecutor.submit)
    threading.Thread.start = _REAL_THREAD_START
    ThreadPoolExecutor.submit = _REAL_POOL_SUBMIT
    try:
        yield
    finally:
        threading.Thread.start, ThreadPoolExecutor.submit = saved

@pytest.fixture(autouse=True)
def patch_threads(request):
    """Patch ThreadPoolExecutor.submit and Thread.start to no-ops.

    Applied to every test automatically. Prevents background threads from
    keeping the process alive after a test completes. ``heavy`` tests are
    exempt: torch / transformers model loading needs real worker threads.
    """
    if request.node.get_closest_marker("heavy") is not None:
        yield
        return
    noop = MagicMock(return_value=None)
    with (
        patch("concurrent.futures.ThreadPoolExecutor.submit", noop),
        patch("threading.Thread.start", noop),
    ):
        yield


# ── REST API client ───────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_api_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not inherit a developer/Docker GRAPHYN_API_TOKEN into unit tests.

    Host shells that ``source .env`` would otherwise make every unauthenticated
    TestClient call return 401. Auth-gate tests set their own token via fixtures.
    """
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKENS", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKENS_FILE", raising=False)
    # Keep local defaults unless a test overrides.
    if "GRAPHYN_AUTH_REQUIRED" not in __import__("os").environ:
        monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)


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


# ── F19 (F-02): restricted egress is the default ──────────────────────────────
#
# Unit tests use RFC 2606 placeholder hosts (api.example.com, hooks.example.com,
# smtp.example.com …) that do not resolve offline. Map *only* those reserved
# names to a public documentation address so restricted-mode checks still run
# (private / loopback / metadata literals are still blocked for real).

_RFC2606_SUFFIXES = (".example", ".example.com", ".example.org", ".example.net", ".test", ".invalid")


@pytest.fixture(autouse=True)
def _offline_placeholder_dns(monkeypatch):
    import ipaddress as _ip

    try:
        from app.core.trust import egress as _egress
    except Exception:
        yield
        return
    real = _egress._resolve_ips

    def _resolve(hostname: str):
        host = (hostname or "").lower().rstrip(".")
        if host in ("example.com", "example.org", "example.net") or host.endswith(_RFC2606_SUFFIXES):
            return [_ip.ip_address("93.184.216.34")]
        return real(hostname)

    monkeypatch.setattr(_egress, "_resolve_ips", _resolve)
    yield
