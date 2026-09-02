
"""Tests for the if_switch plugin."""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/if_switch/"
NODE_TYPE = "if_switch"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("if_switch_plugins")
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

def test_expression_true(installed_cls):
    node = installed_cls(config={"expression": "output['score'] > 5"}, seed=0)
    out = node.process({"input": {"score": 9}})
    assert out["true"]["score"] == 9
    assert out["false"] is None
    assert out["output"].matched is True


def test_expression_false(installed_cls):
    node = installed_cls(config={"expression": "output['score'] > 5"}, seed=0)
    out = node.process({"input": {"score": 1}})
    assert out["true"] is None
    assert out["false"]["score"] == 1


def test_jsonpath(installed_cls):
    node = installed_cls(config={"jsonpath": "$.ok"}, seed=0)
    out = node.process({"input": {"ok": True}})
    assert out["true"]["ok"] is True
