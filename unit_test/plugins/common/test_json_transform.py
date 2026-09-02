
"""Tests for the json_transform plugin."""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/json_transform/"
NODE_TYPE = "json_transform"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("json_transform_plugins")
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

def test_path(installed_cls):
    node = installed_cls(config={"path": "$.user.name"}, seed=0)
    out = node.process({"input": {"user": {"name": "sam"}}})["output"].data
    assert out == "sam"


def test_mappings(installed_cls):
    node = installed_cls(config={"mappings": [{"from": "$.a.b", "to": "b"}]}, seed=0)
    out = node.process({"input": {"a": {"b": 7}}})["output"].data
    assert out["b"] == 7
