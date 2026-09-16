# unit_test/core/plugins/test_restricted_unpickler.py
"""P0-1: RestrictedUnpickler must refuse builtins.eval / dangerous callables."""
from __future__ import annotations

import io
import pickle

import pytest

from app.core.plugins.isolated_executor import RestrictedUnpickler


def _loads(data: bytes):
    return RestrictedUnpickler(io.BytesIO(data)).load()


def test_refuses_builtins_eval() -> None:
    payload = pickle.dumps((eval, ("1+1",)))
    with pytest.raises(pickle.UnpicklingError, match=r"builtins\.eval"):
        _loads(payload)


def test_refuses_builtins_exec() -> None:
    payload = pickle.dumps((exec, ("x=1",)))
    with pytest.raises(pickle.UnpicklingError, match=r"builtins\.exec"):
        _loads(payload)


def test_allows_safe_builtins_containers() -> None:
    payload = pickle.dumps({"a": [1, 2], "b": (3, 4), "c": {"x": True}})
    assert _loads(payload) == {"a": [1, 2], "b": (3, 4), "c": {"x": True}}
