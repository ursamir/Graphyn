
"""Tests for the object_store plugin (local backend, no boto3)."""
from __future__ import annotations

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
    return reg.get_class(NODE_TYPE)


def test_registers(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


def test_metadata(installed_cls):
    meta = installed_cls.metadata
    assert meta.label and meta.category and meta.version


def test_put_list_get_local(installed_cls, tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("hello store", encoding="utf-8")
    root = tmp_path / "store"
    putter = installed_cls(
        config={"backend": "local", "operation": "put", "root": str(root), "prefix": "docs"},
        seed=0,
    )
    refs = putter.process({"input": [str(src)]})["output"]
    if not isinstance(refs, list):
        refs = [refs]
    assert refs[0].key.startswith("docs/")
    assert Path(refs[0].uri).is_file()

    lister = installed_cls(
        config={"backend": "local", "operation": "list", "root": str(root), "prefix": "docs"},
        seed=0,
    )
    listing = lister.process({"input": None})["output"]
    assert any(k.endswith("src.txt") for k in listing.keys)

    dest = tmp_path / "got.txt"
    getter = installed_cls(
        config={
            "backend": "local",
            "operation": "get",
            "root": str(root),
            "key": refs[0].key,
            "dest": str(dest),
        },
        seed=0,
    )
    got = getter.process({"input": None})["output"]
    assert dest.read_text(encoding="utf-8") == "hello store"
    assert got.backend == "local"


def test_put_chunks(installed_cls, tmp_path):
    node = installed_cls(
        config={"backend": "local", "operation": "put", "root": str(tmp_path / "c"), "prefix": "rag"},
        seed=0,
    )
    chunks = [
        {"text": "alpha", "chunk_id": "c1", "source": "a.md"},
        {"text": "beta", "chunk_id": "c2", "source": "a.md"},
    ]
    refs = node.process({"input": chunks})["output"]
    assert len(refs) == 2
    assert Path(refs[0].uri).read_text(encoding="utf-8") == "alpha"


def test_s3_without_boto3(installed_cls):
    node = installed_cls(config={"backend": "s3", "operation": "list", "bucket": "b"}, seed=0)
    try:
        import boto3  # noqa: F401
        pytest.skip("boto3 present")
    except ImportError:
        with pytest.raises(RuntimeError, match="boto3"):
            node.process({"input": None})
