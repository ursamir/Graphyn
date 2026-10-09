
"""Tests for the doc_parse_chunk plugin (stdlib only)."""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

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
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


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


def _chunks(result):
    return result["output"] if isinstance(result, dict) else result


def test_fixed_strategy_with_overlap(installed_cls, tmp_path):
    (tmp_path / "a.txt").write_text("abcdefghij" * 10)  # 100 chars
    node = installed_cls(config={"path": str(tmp_path), "chunk_strategy": "fixed", "max_chars": 40, "overlap": 10}, seed=0)
    chunks = _chunks(node.process({"input": None}))
    texts = [c.text for c in chunks]
    assert all(len(t) <= 40 for t in texts)
    assert texts[1][:10] == texts[0][-10:]  # 10-char overlap
    assert "".join(t[10:] if i else t for i, t in enumerate(texts)).startswith("abcdefghij" * 9)


def test_recursive_strategy_splits_sentences(installed_cls, tmp_path):
    (tmp_path / "a.txt").write_text(" ".join(f"Sentence number {i} is here." for i in range(30)))
    node = installed_cls(config={"path": str(tmp_path), "chunk_strategy": "recursive", "max_chars": 120}, seed=0)
    texts = [c.text for c in _chunks(node.process({"input": None}))]
    assert len(texts) > 3
    assert all(len(t) <= 120 for t in texts)
    assert all(t.rstrip().endswith(".") for t in texts[:-1])  # cut at sentence boundaries


def test_metadata_keys(installed_cls, tmp_path):
    (tmp_path / "doc.md").write_text("# T\n\nbody")
    node = installed_cls(config={"path": str(tmp_path), "metadata_keys": ["name", "size"]}, seed=0)
    meta = _chunks(node.process({"input": None}))[0].metadata
    assert meta["name"] == "doc.md" and meta["size"] > 0 and meta["suffix"] == ".md"
    bad = installed_cls(config={"path": str(tmp_path), "metadata_keys": ["author"]}, seed=0)
    with pytest.raises(ValueError, match="unknown metadata key"):
        bad.process({"input": None})


def test_use_unstructured_missing_is_clear(installed_cls, tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("unstructured"):
            raise ImportError("no unstructured")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    (tmp_path / "a.txt").write_text("hello")
    node = installed_cls(config={"path": str(tmp_path), "use_unstructured": True}, seed=0)
    with pytest.raises(RuntimeError, match="unstructured"):
        node.process({"input": None})


def test_accepts_wrapped_and_dict_paths(installed_cls, tmp_path):
    """F-06 payload contract: paths inside python_code wrappers / {path} dicts are read."""
    doc = tmp_path / "w.txt"
    doc.write_text("alpha beta gamma " * 50)
    node = installed_cls(config={"max_chars": 120, "chunk_strategy": "fixed"}, seed=0)
    wrapped = node.process({"input": {"data": {"path": str(doc)}, "metadata": {}}})["output"]
    assert len(wrapped) > 1
    assert all("alpha" in c.text or "gamma" in c.text for c in wrapped)
    listed = node.process({"input": [{"path": str(doc)}]})["output"]
    assert [c.text for c in listed] == [c.text for c in wrapped]
