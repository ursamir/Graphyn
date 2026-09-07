"""Distributed transfer: pickle port values + blob put/get."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _tmp_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    yield


def test_dump_load_port_value_round_trip():
    from app.core.distributed.transfer import dump_port_value, load_port_value

    payload = {"items": [1, 2, 3], "label": "ok", "nested": {"a": True}}
    raw = dump_port_value(payload)
    assert isinstance(raw, bytes)
    assert load_port_value(raw) == payload


def test_put_get_blob_round_trip():
    from app.core.distributed.transfer import get_blob, put_blob, put_port_value, get_port_value

    uri = put_blob(b"hello-distributed")
    assert uri.startswith("artifact://local/")
    assert get_blob(uri) == b"hello-distributed"

    uri2 = put_blob(b"hello-distributed")
    assert uri2 == uri

    port_uri = put_port_value({"x": 42})
    assert get_port_value(port_uri) == {"x": 42}


def test_put_blob_rejects_empty():
    from app.core.distributed.transfer import put_blob

    with pytest.raises(ValueError):
        put_blob(b"")
