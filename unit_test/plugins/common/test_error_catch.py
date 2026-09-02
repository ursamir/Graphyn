
"""Tests for the error_catch plugin."""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/error_catch/"
NODE_TYPE = "error_catch"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("error_catch_plugins")
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

from app.core.node_executor import NodeExecutor


def test_passthrough(installed_cls):
    node = installed_cls(config={}, seed=0)
    out = node.process({"input": {"ok": True}})
    assert out["output"]["ok"] is True
    assert out["error"] is None


def test_error_input(installed_cls):
    node = installed_cls(config={}, seed=0)
    out = node.process({"input": None, "error": {"message": "boom"}})
    assert out["output"] is None
    assert out["error"]["message"] == "boom"


def test_executor_continue_on_error(installed_cls):
    class Boom(installed_cls):
        def process(self, inputs):
            raise ValueError("intentional")

    node = Boom(config={"on_error": "continue_error_output", "on_error_port": "error"}, seed=0)
    exec_ = NodeExecutor(node, run_id="t")
    exec_.setup()
    try:
        out = exec_.execute({"input": {"a": 1}})
    finally:
        exec_.teardown()
    assert out["error"]["error_type"] == "ValueError"
    assert "intentional" in out["error"]["message"]
