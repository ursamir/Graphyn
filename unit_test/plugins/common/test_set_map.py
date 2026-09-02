
"""Tests for the set_map plugin."""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/set_map/"
NODE_TYPE = "set_map"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("set_map_plugins")
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

def test_rename_drop_copy(installed_cls):
    node = installed_cls(config={
        "copy_fields": {"a": "a_copy"},
        "rename": {"b": "bee"},
        "drop": ["c"],
        "set": {"z": 1},
    }, seed=0)
    out = node.process({"input": {"a": 1, "b": 2, "c": 3}})["output"].data
    assert out["a"] == 1
    assert out["a_copy"] == 1
    assert out["bee"] == 2
    assert "b" not in out
    assert "c" not in out
    assert out["z"] == 1


def test_list(installed_cls):
    node = installed_cls(config={"drop": ["x"]}, seed=0)
    out = node.process({"input": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]})["output"].data
    assert out == [{"y": 2}, {"y": 4}]
