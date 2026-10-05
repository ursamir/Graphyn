
"""Tests for the csv_table plugin."""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/csv_table/"
NODE_TYPE = "csv_table"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("csv_table_plugins")
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


def test_write_read(installed_cls, ws):
    path = "tables/t.csv"
    writer = installed_cls(config={"operation": "write", "path": path}, seed=0)
    rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    written = writer.process({"input": rows})["output"]
    assert written.row_count == 2
    assert (ws / "tables" / "t.csv").is_file()
    pub = writer.take_published_file_trees()
    assert pub and pub[0]["files"][0]["path"] == "t.csv"
    reader = installed_cls(config={"operation": "read", "path": path}, seed=0)
    read = reader.process({})["output"]
    assert read.row_count == 2
    assert read.rows[0]["a"] == "1"


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.csv", "a/../../x.csv", "C:/x.csv", "~/x.csv"])
def test_path_jail_rejects_absolute_and_dotdot(installed_cls, ws, bad):
    node = installed_cls(config={"operation": "read", "path": bad}, seed=0)
    with pytest.raises(RuntimeError, match="absolute|\\.\\.|outside"):
        node.process({})


def test_path_jail_rejects_symlink_escape(installed_cls, ws, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "x.csv").write_text("a\n1\n")
    (ws / "link").symlink_to(outside, target_is_directory=True)
    node = installed_cls(config={"operation": "read", "path": "link/x.csv"}, seed=0)
    with pytest.raises(RuntimeError, match="outside"):
        node.process({})
