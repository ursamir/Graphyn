
"""Tests for the object_store plugin (local backend, no boto3)."""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

from pathlib import Path

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/object_store/"
NODE_TYPE = "object_store"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("object_store_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


def test_registers(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


def test_metadata(installed_cls):
    meta = installed_cls.metadata
    assert meta.label and meta.category and meta.version


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    return tmp_path


def test_put_list_get_local(installed_cls, ws):
    src = ws / "src.txt"
    src.write_text("hello store", encoding="utf-8")
    root = "artifacts/store"
    putter = installed_cls(
        config={"backend": "local", "operation": "put", "root": root, "prefix": "docs"},
        seed=0,
    )
    refs = putter.process({"input": [str(src)]})["output"]
    if not isinstance(refs, list):
        refs = [refs]
    assert refs[0].key.startswith("docs/")
    assert Path(refs[0].uri).is_file()
    assert Path(refs[0].uri).is_relative_to(ws)
    pub = putter.take_published_file_trees()
    assert pub and pub[0]["files"][0]["path"] == "docs/src.txt"

    lister = installed_cls(
        config={"backend": "local", "operation": "list", "root": root, "prefix": "docs"},
        seed=0,
    )
    listing = lister.process({"input": None})["output"]
    assert any(k.endswith("src.txt") for k in listing.keys)

    getter = installed_cls(
        config={
            "backend": "local",
            "operation": "get",
            "root": root,
            "key": refs[0].key,
            "dest": "out/got.txt",
        },
        seed=0,
    )
    got = getter.process({"input": None})["output"]
    assert (ws / "out" / "got.txt").read_text(encoding="utf-8") == "hello store"
    assert got.backend == "local"


def test_put_chunks(installed_cls, ws):
    node = installed_cls(
        config={"backend": "local", "operation": "put", "root": "c", "prefix": "rag"},
        seed=0,
    )
    chunks = [
        {"text": "alpha", "chunk_id": "c1", "source": "a.md"},
        {"text": "beta", "chunk_id": "c2", "source": "a.md"},
    ]
    refs = node.process({"input": chunks})["output"]
    assert len(refs) == 2
    assert Path(refs[0].uri).read_text(encoding="utf-8") == "alpha"


def test_default_root_is_workspace_artifacts(installed_cls, ws):
    node = installed_cls(config={"operation": "put", "key": "note.txt"}, seed=0)
    ref = node.process({"input": "hi"})["output"]
    assert Path(ref.uri) == (ws / "artifacts" / "object_store" / "note.txt").resolve()


@pytest.mark.parametrize("cfg", [
    {"operation": "list", "root": "/tmp"},
    {"operation": "list", "root": "../escape"},
    {"operation": "get", "key": "../../etc/passwd"},
    {"operation": "get", "key": "/etc/passwd"},
    {"operation": "put", "key": "../x.txt"},
])
def test_jail_rejects_escapes(installed_cls, ws, cfg):
    node = installed_cls(config={"backend": "local", **cfg}, seed=0)
    with pytest.raises(RuntimeError, match="absolute|\\.\\.|outside|invalid|escapes"):
        node.process({"input": "x"})


def test_get_dest_absolute_rejected(installed_cls, ws):
    installed_cls(config={"operation": "put", "key": "k.txt"}, seed=0).process({"input": "v"})
    node = installed_cls(config={"operation": "get", "key": "k.txt", "dest": "/tmp/stolen.txt"}, seed=0)
    with pytest.raises(RuntimeError, match="absolute"):
        node.process({"input": None})


def test_put_input_outside_workspace_rejected(installed_cls, ws, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("s")
    node = installed_cls(config={"operation": "put"}, seed=0)
    with pytest.raises(RuntimeError, match="outside"):
        node.process({"input": [str(outside)]})


def test_s3_without_boto3(installed_cls):
    node = installed_cls(config={"backend": "s3", "operation": "list", "bucket": "b"}, seed=0)
    try:
        import boto3  # noqa: F401
        pytest.skip("boto3 present")
    except ImportError:
        with pytest.raises(RuntimeError, match="boto3"):
            node.process({"input": None})
