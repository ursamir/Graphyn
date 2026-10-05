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


# ── recipient allowlist / payload recipients (review fixes) ──────────────────

def test_payload_recipients_refused_by_default(installed_cls, monkeypatch):
    monkeypatch.setenv("GRAPHYN_SMTP_DRY_RUN", "1")
    node = installed_cls(config={}, seed=0)
    with pytest.raises(ValueError, match="allow_payload_recipients"):
        node.process({"input": {"to": "attacker@evil.example", "body": "x"}})


def test_payload_recipients_opt_in(installed_cls, monkeypatch):
    monkeypatch.setenv("GRAPHYN_SMTP_DRY_RUN", "1")
    node = installed_cls(config={"allow_payload_recipients": True,
                                 "allowed_recipient_domains": ["example.com"]}, seed=0)
    out = node.process({"input": {"to": "a@team.example.com", "body": "x"}})["output"]
    assert out.to == ["a@team.example.com"]
    with pytest.raises(ValueError, match="allowed_recipient_domains"):
        node.process({"input": {"to": "a@evil.example", "body": "x"}})


def test_config_recipient_domain_allowlist_and_injection(installed_cls, monkeypatch):
    monkeypatch.setenv("GRAPHYN_SMTP_DRY_RUN", "1")
    node = installed_cls(config={"to": "x@other.org", "allowed_recipient_domains": ["example.com"]}, seed=0)
    with pytest.raises(ValueError, match="allowed_recipient_domains"):
        node.process({"input": {"body": "x"}})
    bad = installed_cls(config={"to": "a@example.com\nBcc: z@evil.example"}, seed=0)
    with pytest.raises(ValueError, match="invalid recipient"):
        bad.process({"input": {"body": "x"}})


def test_payload_from_ignored_without_opt_in(installed_cls, monkeypatch):
    monkeypatch.setenv("GRAPHYN_SMTP_DRY_RUN", "1")
    node = installed_cls(config={"to": "ops@example.com"}, seed=0)
    out = node.process({"input": {"from": "ceo@bank.example", "body": "x"}})["output"]
    assert out.from_addr != "ceo@bank.example"
    assert node.take_external_calls() == []  # dry-run: no egress recorded


def test_smtp_send_recorded(installed_cls, monkeypatch):
    from unittest.mock import MagicMock, patch
    monkeypatch.delenv("GRAPHYN_SMTP_DRY_RUN", raising=False)
    monkeypatch.setenv("GRAPHYN_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("GRAPHYN_SMTP_FROM", "bot@example.com")
    node = installed_cls(config={"to": "ops@example.com"}, seed=0)
    with patch("smtplib.SMTP", MagicMock()):
        node.process({"input": {"body": "x"}})
    calls = node.take_external_calls()
    assert calls and calls[0]["kind"] == "smtp" and calls[0]["url"].startswith("smtp://smtp.example.com")
