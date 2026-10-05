"""Tests for the webhook_trigger plugin (inbound webhook source node)."""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class

PLUGIN_SOURCE = "PluginPackage/Common/webhook_trigger/"
NODE_TYPE = "webhook_trigger"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("webhook_trigger_plugins")
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


def test_ports_and_metadata(installed_cls):
    assert set(installed_cls.output_ports) == {"body", "headers", "query"}
    assert all(not p.required for p in installed_cls.input_ports.values())
    assert installed_cls.metadata.cacheable is False


def test_passes_injected_payload(installed_cls):
    node = installed_cls(config={}, seed=0)
    out = node.process({
        "body": {"event": "push"},
        "headers": {"content-type": "application/json", "x-github-event": "push"},
        "query": {"ref": "main"},
    })
    assert out["body"] == {"event": "push"}
    assert out["headers"]["x-github-event"] == "push"
    assert out["query"] == {"ref": "main"}


def test_header_allowlist_and_sample_body(installed_cls):
    node = installed_cls(
        config={"header_allowlist": ["content-type"], "sample_body": {"demo": 1}}, seed=0
    )
    out = node.process({"headers": {"content-type": "a", "user-agent": "b"}})
    assert out["headers"] == {"content-type": "a"}
    assert out["body"] == {"demo": 1}
    assert out["query"] == {}
