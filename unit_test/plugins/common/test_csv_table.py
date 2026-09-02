
"""Tests for the csv_table plugin."""
from __future__ import annotations

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
    return reg.get_class(NODE_TYPE)


def test_registers(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


def test_metadata(installed_cls):
    meta = installed_cls.metadata
    assert meta.label and meta.category and meta.version

def test_write_read(installed_cls, tmp_path):
    path = tmp_path / "t.csv"
    writer = installed_cls(config={"operation": "write", "path": str(path)}, seed=0)
    rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    written = writer.process({"input": rows})["output"]
    assert written.row_count == 2
    reader = installed_cls(config={"operation": "read", "path": str(path)}, seed=0)
    read = reader.process({})["output"]
    assert read.row_count == 2
    assert read.rows[0]["a"] == "1"
