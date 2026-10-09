"""F19 (F-01): materialize_artifact_refs must bind its root on the normal path."""
from __future__ import annotations

import pytest

from app.core.distributed import transfer


def test_materialize_plain_value_normal_path(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHYN_RESIDENCY_ENFORCE", raising=False)
    value = {"a": 1, "b": [1, 2, "x"]}
    out = transfer.materialize_artifact_refs(value, materialize_dir=tmp_path, port="input")
    assert out == value


def test_materialize_default_root_normal_path(monkeypatch):
    monkeypatch.delenv("GRAPHYN_RESIDENCY_ENFORCE", raising=False)
    assert transfer.materialize_artifact_refs("hello") == "hello"


def test_residency_error_still_propagates(tmp_path, monkeypatch):
    from app.core.trust.residency import ResidencyError

    monkeypatch.setenv("GRAPHYN_RESIDENCY_ENFORCE", "1")
    monkeypatch.setenv("GRAPHYN_RESIDENCY_REGION", "eu")
    monkeypatch.setenv("GRAPHYN_ACTIVE_ORG_REGION", "us")
    with pytest.raises(ResidencyError):
        transfer.materialize_artifact_refs({"a": 1}, materialize_dir=tmp_path)
