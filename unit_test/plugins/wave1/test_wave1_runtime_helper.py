"""Unit tests for Wave-1 venv helpers (no heavy deps required)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.plugins.wave1_runtime import (
    WAVE1_CAPABILITIES,
    install_hint,
    probe_import,
    resolve_wave1_venv,
    want_real_backend,
    wave1_venvs_root,
)


def test_capabilities_env_keys():
    assert set(WAVE1_CAPABILITIES) == {"vision", "tinyml", "rag"}
    assert WAVE1_CAPABILITIES["vision"] == "GRAPHYN_WAVE1_VENV_VISION"


def test_install_hint_mentions_script():
    msg = install_hint("vision", ["ultralytics>=8.0"])
    assert "install_wave1_plugin_venvs.sh" in msg
    assert "GRAPHYN_WAVE1_VENV_VISION" in msg
    assert "ultralytics" in msg


def test_want_real_backend_stub_true():
    use_real, err = want_real_backend(True, "definitely_missing_mod_xyz")
    assert use_real is False
    assert err is None


def test_want_real_backend_missing_import():
    use_real, err = want_real_backend(False, "definitely_missing_mod_xyz")
    assert use_real is False
    assert err == "missing"


def test_probe_import_stdlib():
    assert probe_import("json", "pathlib") is True
    assert probe_import("definitely_missing_mod_xyz") is False


def test_resolve_wave1_venv_from_env(tmp_path, monkeypatch):
    venv = tmp_path / "wave1-vision"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    py = bin_dir / "python"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    monkeypatch.setenv("GRAPHYN_WAVE1_VENV_VISION", str(venv))
    assert resolve_wave1_venv("vision") == venv.resolve()


def test_wave1_venvs_root_override(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_WAVE1_VENVS_ROOT", str(tmp_path))
    assert wave1_venvs_root() == tmp_path.resolve()
