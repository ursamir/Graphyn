"""Wave 5: container plugin sandbox status + mode selection."""
from __future__ import annotations

import shutil

import pytest

from app.core.plugins.container_sandbox import (
    plugin_isolation_mode,
    sandbox_network_mode,
    sandbox_status,
)


def test_default_isolation_is_subprocess(monkeypatch):
    monkeypatch.delenv("GRAPHYN_PLUGIN_ISOLATION", raising=False)
    assert plugin_isolation_mode() == "subprocess"
    st = sandbox_status()
    assert st["isolation_mode"] == "subprocess"
    assert "Not shipped" in st["tee_sgx"]


def test_container_mode_detects_runtime(monkeypatch):
    monkeypatch.setenv("GRAPHYN_PLUGIN_ISOLATION", "container")
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_ALLOWLIST", "api.example.com")
    st = sandbox_status()
    assert st["isolation_mode"] == "container"
    assert st["egress_allowlist_set"] is True
    assert sandbox_network_mode() == "allowlist"
    # docker is present on Server-99
    if shutil.which("docker") or shutil.which("podman"):
        assert st["runtime"] in ("docker", "podman")
        assert st["runtime_error"] is None
    else:
        assert st["runtime_error"]


def test_network_none(monkeypatch):
    monkeypatch.setenv("GRAPHYN_PLUGIN_SANDBOX_NETWORK", "none")
    assert sandbox_network_mode() == "none"
