"""Regression: RestrictedUnpickler must refuse dotted STACK_GLOBAL names."""
from __future__ import annotations

import io
import pickle

import pytest

from app.core.plugins.isolated_executor import RestrictedUnpickler


def _sg(module: str, name: str) -> bytes:
    """Protocol-4 payload: STACK_GLOBAL(module, name)() ."""
    def u(s: str) -> bytes:
        b = s.encode()
        return b"\x8c" + bytes([len(b)]) + b

    return b"\x80\x04" + u(module) + u(name) + b"\x93" + b")" + b"R" + b"."


def _loads(data: bytes):
    return RestrictedUnpickler(io.BytesIO(data)).load()


@pytest.mark.parametrize(
    "module,name",
    [
        ("numpy", "_pytesttester.os.getpid"),
        ("numpy", "testing.os.getpid"),
        ("builtins", "str.join"),
        ("app.models.audio", "os.getpid"),
        ("app.models.audio", "_private"),
        ("numpy", "_pytesttester"),
        ("numpy", "memmap"),
        ("numpy", "fromfile"),
    ],
)
def test_refuses_traversal_and_private(module, name):
    with pytest.raises(pickle.UnpicklingError):
        _loads(_sg(module, name))


def test_numpy_array_roundtrip_still_works():
    np = pytest.importorskip("numpy")
    arr = np.arange(6, dtype="float32").reshape(2, 3)
    for proto in (4, 5):  # worker uses HIGHEST_PROTOCOL
        out = _loads(pickle.dumps({"a": arr, "s": np.float64(1.5)}, protocol=proto))
        assert (out["a"] == arr).all() and out["s"] == 1.5


def test_masked_array_roundtrip():
    np = pytest.importorskip("numpy")
    m = np.ma.masked_array([1, 2, 3], mask=[0, 1, 0])
    out = _loads(pickle.dumps(m))
    assert list(out.mask) == [False, True, False]
