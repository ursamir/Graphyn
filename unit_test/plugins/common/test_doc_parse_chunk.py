
"""Tests for the doc_parse_chunk plugin (stdlib only)."""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/doc_parse_chunk/"
NODE_TYPE = "doc_parse_chunk"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("doc_parse_chunk_plugins")
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


def test_empty_path(installed_cls):
    node = installed_cls(config={"path": ""}, seed=0)
    assert node.process({"input": None})["output"] == []


def test_parse_md_and_txt_folder(installed_cls, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.md").write_text("# Title\n\nHello world.\n\n## Second\n\nMore text.\n", encoding="utf-8")
    (folder / "b.txt").write_text("Plain paragraph one.\n\nPlain paragraph two.\n", encoding="utf-8")
    (folder / "ignore.bin").write_bytes(b"\x00\x01")
    node = installed_cls(config={"path": str(folder), "max_chars": 200}, seed=0)
    chunks = node.process({"input": None})["output"]
    assert chunks
    texts = " ".join(c.text for c in chunks)
    assert "Hello world" in texts
    assert "Plain paragraph" in texts
    assert all(c.chunk_id and c.source for c in chunks)


def test_html_strips_tags(installed_cls, tmp_path):
    html = tmp_path / "x.html"
    html.write_text("<html><body><h1>Hi</h1><p>There</p></body></html>", encoding="utf-8")
    node = installed_cls(config={"path": str(html)}, seed=0)
    chunks = node.process({"input": None})["output"]
    blob = " ".join(c.text for c in chunks)
    assert "Hi" in blob and "There" in blob
    assert "<p>" not in blob
