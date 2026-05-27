"""Unit tests for app/core/runtime_backend.py — Req 19 criteria 12–17."""
from __future__ import annotations

import pytest

from app.core.runtime_backend import (
    LocalPythonBackend,
    RuntimeBackend,
    _reset_backend_registry,
    get_backend,
    list_backends,
    register_backend,
)


# ── get_backend ───────────────────────────────────────────────────────────────

def test_get_backend_local_python_returns_local_python_backend():
    """Req 19.12 — get_backend('local_python') returns a LocalPythonBackend."""
    backend = get_backend("local_python")
    assert isinstance(backend, LocalPythonBackend)


def test_get_backend_nonexistent_raises_value_error():
    """Req 19.13 — get_backend('nonexistent') raises ValueError."""
    with pytest.raises(ValueError):
        get_backend("nonexistent")


# ── list_backends ─────────────────────────────────────────────────────────────

def test_list_backends_returns_sorted_list_containing_local_python():
    """Req 19.14 — list_backends() returns a sorted list containing 'local_python'."""
    backends = list_backends()
    assert isinstance(backends, list)
    assert "local_python" in backends
    assert backends == sorted(backends)


# ── register_backend ─────────────────────────────────────────────────────────

def test_register_backend_makes_get_backend_succeed():
    """Req 19.15 — register_backend('my_backend', LocalPythonBackend) makes get_backend succeed."""
    register_backend("my_backend", LocalPythonBackend)
    try:
        backend = get_backend("my_backend")
        assert isinstance(backend, LocalPythonBackend)
    finally:
        _reset_backend_registry()


def test_register_backend_non_subclass_raises_type_error():
    """Req 19.16 — register_backend('x', int) raises TypeError."""
    with pytest.raises(TypeError):
        register_backend("x", int)


# ── LocalPythonBackend.backend_id ─────────────────────────────────────────────

def test_local_python_backend_id_returns_local_python():
    """Req 19.17 — LocalPythonBackend().backend_id returns 'local_python'."""
    backend = LocalPythonBackend()
    assert backend.backend_id == "local_python"
