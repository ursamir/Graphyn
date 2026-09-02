
"""Tests for the eval_gate plugin."""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/eval_gate/"
NODE_TYPE = "eval_gate"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("eval_gate_plugins")
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


def test_pass_through(installed_cls):
    node = installed_cls(config={"required_keys": ["pain"]}, seed=0)
    payload = {"data": {"pain": "x", "owner": "sam"}, "text": "ok"}
    out = node.process({"input": payload})
    assert out["output"] is payload
    assert out["report"].passed is True


def test_empty_transcript_fails(installed_cls):
    node = installed_cls(config={"check_empty_transcript": True}, seed=0)
    with pytest.raises(RuntimeError, match="empty transcript"):
        node.process({"input": {"text": "  "}})


def test_missing_keys_fail(installed_cls):
    node = installed_cls(
        config={"check_empty_transcript": False, "required_keys": ["pain", "owner"]},
        seed=0,
    )
    with pytest.raises(RuntimeError, match="missing required keys"):
        node.process({"input": {"data": {"pain": "x"}}})


def test_pii_residual_fail(installed_cls):
    node = installed_cls(
        config={"check_empty_transcript": False, "pii_regex": "[0-9]{3}-[0-9]{2}-[0-9]{4}"},
        seed=0,
    )
    with pytest.raises(RuntimeError, match="residual PII"):
        node.process({"input": {"text": "ssn 123-45-6789"}})
