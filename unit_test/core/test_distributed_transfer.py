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


def test_safe_path_rejects_escape(tmp_path, monkeypatch):
    from app.core.distributed import transfer as tr

    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    with pytest.raises(ValueError):
        tr._safe_path("../etc/passwd")
    with pytest.raises(ValueError):
        tr._safe_path("sha256/../../etc/passwd")


def test_put_get_nested_content_addressed_key(tmp_path, monkeypatch):
    """Nested sha256/ab/cd/... keys round-trip via put_blob/get_blob."""
    from app.core.artifact_uri import local_content_key
    from app.core.distributed.transfer import get_blob, http_get_blob, put_blob
    from urllib.parse import quote as url_quote

    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    body = b"nested-key-payload-xyz"
    # Explicit nested key shaped like content-addressed layout.
    key = local_content_key("abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789")
    assert key.startswith("sha256/")
    assert "/" in key
    uri = put_blob(body, key=key)
    assert key in uri
    assert get_blob(uri) == body

    # http_get_blob must URL-encode the key (safe="/") so nested paths survive.
    # We only assert the URL construction contract here (no live HTTP server).
    from app.core.distributed import transfer as tr

    captured = {}

    class _Resp:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=60.0):
        captured["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(tr.urllib.request, "urlopen", fake_urlopen)
    got = http_get_blob("http://control.example/api/v1", uri)
    assert got == body
    assert "sha256/" in captured["url"]
    # Encoded form should match quote(key, safe="/")
    assert url_quote(key, safe="/") in captured["url"]
