
"""Tests for the merge plugin."""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/merge/"
NODE_TYPE = "merge"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("merge_plugins")
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

def test_append(installed_cls):
    node = installed_cls(config={"mode": "append"}, seed=0)
    out = node.process({"a": [1], "b": [2, 3]})["output"].data
    assert out == [1, 2, 3]


def test_combine_by_key(installed_cls):
    node = installed_cls(config={"mode": "combine_by_key", "key": "id"}, seed=0)
    out = node.process({
        "a": [{"id": 1, "x": 1}, {"id": 2, "x": 2}],
        "b": [{"id": 2, "y": 9}],
    })["output"].data
    assert out[0]["id"] == 1
    assert out[1]["x"] == 2 and out[1]["y"] == 9
