"""Tests for send_email SMTP plugin (dry-run / needs-credentials)."""
from __future__ import annotations

import pytest

from unit_test.plugins._helpers import materialize_isolated_class
from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/send_email/"
NODE_TYPE = "send_email"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("send_email_plugins")
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


def test_dry_run_config(installed_cls, monkeypatch):
    monkeypatch.delenv("GRAPHYN_SMTP_HOST", raising=False)
    node = installed_cls(config={"to": "ops@example.com", "subject": "hi", "dry_run": True}, seed=0)
    out = node.process({"input": {"body": "hello"}})["output"]
    assert out.ok is True
    assert out.dry_run is True
    assert out.to == ["ops@example.com"]


def test_dry_run_env(installed_cls, monkeypatch):
    monkeypatch.setenv("GRAPHYN_SMTP_DRY_RUN", "1")
    monkeypatch.delenv("GRAPHYN_SMTP_HOST", raising=False)
    node = installed_cls(config={"to": "ops@example.com"}, seed=0)
    out = node.process({"input": "plain text body"})["output"]
    assert out.dry_run is True


def test_missing_smtp_fails_closed(installed_cls, monkeypatch):
    monkeypatch.delenv("GRAPHYN_SMTP_DRY_RUN", raising=False)
    monkeypatch.delenv("GRAPHYN_SMTP_HOST", raising=False)
    monkeypatch.delenv("GRAPHYN_SMTP_FROM", raising=False)
    node = installed_cls(config={"to": "ops@example.com", "dry_run": False}, seed=0)
    with pytest.raises(RuntimeError, match="needs-credentials"):
        node.process({"input": {"body": "x"}})
