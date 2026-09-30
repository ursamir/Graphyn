"""Security regressions: webhook/audit/plugin-source leaks, dataset traversal,
scp-style plugin sources, git transport lockdown, CGNAT egress blocking."""
from __future__ import annotations

import ipaddress
import json
import logging
from unittest.mock import patch

import pytest

SECRET_URL = "https://hooks.example.com/services/T0K3N/SECRETPATH?sig=QQQ"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    w = tmp_path / "workspace"
    w.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(w))
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    from app.core.notify.webhook import WebhookService

    WebhookService._class_config_cache = None
    yield w
    WebhookService._class_config_cache = None


def _write_webhook(ws):
    (ws / "webhooks.json").write_text(json.dumps({"url": SECRET_URL, "events": []}), encoding="utf-8")


# ── 4. webhook / audit leaks ────────────────────────────────────────────────

def test_mcp_get_webhooks_redacted(ws):
    from app.mcp.handlers.journey import get_webhooks_handler

    _write_webhook(ws)
    out = get_webhooks_handler({})
    assert "T0K3N" not in json.dumps(out)
    assert out["url"].startswith("https://hooks.example.com")
    assert out["url_configured"] is True


def test_mcp_put_webhooks_redacted(ws):
    from app.mcp.handlers.journey import put_webhooks_handler

    with patch("app.core.notify.webhook.WebhookService.save", return_value={}):
        out = put_webhooks_handler({"url": SECRET_URL, "events": ["run.completed"]})
    assert "T0K3N" not in json.dumps(out)
    from app.core.trust.audit import audit_events_path

    raw = audit_events_path().read_text(encoding="utf-8")
    assert "T0K3N" not in raw


def test_mcp_test_webhook_redacted(ws):
    from app.mcp.handlers.journey import test_webhook_handler

    _write_webhook(ws)
    with patch("app.core.notify.webhook.WebhookService.notify"):
        out = test_webhook_handler({})
    assert "T0K3N" not in json.dumps(out)
    from app.core.trust.audit import audit_events_path

    assert "T0K3N" not in audit_events_path().read_text(encoding="utf-8")


def test_export_audit_always_normalized(ws):
    from app.core.trust.audit import audit_events_path
    from app.mcp.handlers.audit_ops import export_audit_handler

    p = audit_events_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"action": "webhook.set", "resource_type": "webhook", "resource_id": SECRET_URL}) + "\n",
        encoding="utf-8",
    )
    for limit in (10, 10000, 99999):
        out = export_audit_handler({"limit": limit})
        assert "T0K3N" not in out["content"]
        assert out["count"] == 1


def test_egress_errors_do_not_embed_url():
    from app.core.trust.egress import HttpEgressError, validate_http_egress_url, validated_webhook_ips

    with pytest.raises(HttpEgressError) as ei:
        validate_http_egress_url("ftp://u:pw@host.example/T0K3N", mode="restricted")
    assert "T0K3N" not in str(ei.value) and "pw" not in str(ei.value)
    with pytest.raises(ValueError) as ei2:
        validated_webhook_ips("https://127.0.0.1/hooks/T0K3N")
    assert "T0K3N" not in str(ei2.value)
    with pytest.raises(ValueError) as ei3:
        validated_webhook_ips("ftp://x.example/hooks/T0K3N")
    assert "T0K3N" not in str(ei3.value)


def test_webhook_send_failure_log_redacted(caplog):
    from app.core.notify.webhook import WebhookService

    class Boom(Exception):
        pass

    def _raise(*a, **k):
        raise Boom(f"Client error '404' for url '{SECRET_URL}' and 'https://1.2.3.4/services/T0K3N'")

    with patch("app.core.trust.egress.validated_webhook_ips", side_effect=_raise):
        with caplog.at_level(logging.WARNING, logger="app.core.notify.webhook"):
            WebhookService()._send(SECRET_URL, "evt", {})
    assert caplog.records
    assert "T0K3N" not in caplog.text


# ── 5. plugin source userinfo ───────────────────────────────────────────────

def test_mcp_plugin_error_redacts_userinfo():
    from app.mcp.handlers.plugins import _error

    out = _error(RuntimeError("clone failed for 'https://user:TOKENX@github.com/o/r.git'"))
    assert "TOKENX" not in out["message"]


def test_manager_persists_redacted_source(tmp_path, monkeypatch, caplog):
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    mgr = PluginManager(registry=NodeRegistry(), base_dir=str(tmp_path))
    mgr._plugins_dir = str(tmp_path)
    real_resolve = mgr._installer.resolve
    seen = {}

    def _fake_resolve(source, **kw):
        seen["source"] = source
        return real_resolve("PluginPackage/Common/merge/", **kw)

    monkeypatch.setattr(mgr._installer, "resolve", _fake_resolve)
    with caplog.at_level(logging.INFO):
        rec = mgr.install("https://user:TOKENX@github.com/o/merge.git")
    assert seen["source"] == "https://user:TOKENX@github.com/o/merge.git"  # real source used for fetch
    assert "TOKENX" not in rec.source
    assert "TOKENX" not in caplog.text
    reg = (tmp_path / "registry.json")
    blobs = [p.read_text(encoding="utf-8") for p in tmp_path.rglob("registry.json")] or [""]
    assert all("TOKENX" not in b for b in blobs)
    assert reg is not None


# ── 6. dataset traversal ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "args",
    [
        {"project": "../../etc", "version": "v1"},
        {"project": "ok", "version": "../../../tmp"},
        {"project": "ok", "version": "v1/../../x"},
        {"project": "..", "version": "v1"},
    ],
)
def test_mcp_dataset_version_traversal_rejected(ws, args):
    from app.mcp.handlers.data_ops import get_dataset_version_handler

    out = get_dataset_version_handler(args)
    assert out.get("error") is True and out["error_type"] == "validation_failed"


def test_mcp_list_versions_traversal_rejected(ws):
    from app.mcp.handlers.data_ops import list_dataset_versions_handler

    out = list_dataset_versions_handler({"project": "../.."})
    assert out.get("error") is True


def test_quality_checker_rejects_traversal(ws, tmp_path):
    from app.domain.quality_checker import QualityChecker

    out = QualityChecker().run("proj", "../../../escape")
    assert out and out[0]["check_name"] == "invalid_target"
    assert not (tmp_path / "escape").exists()
    assert not list(tmp_path.rglob("quality_report.json"))


# ── 7. scp-style plugin sources + git transport lockdown ────────────────────

@pytest.mark.parametrize("src", ["git@github.com:evil/x.git", "evil.com:x.git", "ext::sh -c id"])
def test_scp_style_sources_are_remote_and_denied(monkeypatch, src):
    from app.core.config import _looks_like_remote_plugin_source, plugin_source_is_allowed
    from app.core.plugins.errors import PluginInstallError
    from app.core.plugins.installer import PluginInstaller

    monkeypatch.setenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", "https://github.com/trusted/repo")
    assert _looks_like_remote_plugin_source(src) is True
    assert plugin_source_is_allowed(src) is False
    with patch("subprocess.run") as run:
        with pytest.raises(PluginInstallError):
            PluginInstaller().resolve(src)
        run.assert_not_called()


@pytest.mark.parametrize("src", ["PluginPackage/Common/merge/", "/abs/path/x", "./a:b", "my-plugin"])
def test_local_sources_still_local(src):
    from app.core.config import _looks_like_remote_plugin_source

    assert _looks_like_remote_plugin_source(src) is False


def test_git_clone_uses_protocol_lockdown(monkeypatch):
    from app.core.plugins.errors import PluginInstallError
    from app.core.plugins.installer import PluginInstaller

    class R:
        returncode = 1
        stderr = "nope"

    with patch("app.core.plugins.installer.shutil.which", return_value="/usr/bin/git"), \
            patch("app.core.plugins.installer.subprocess.run", return_value=R()) as run:
        with pytest.raises(PluginInstallError):
            PluginInstaller()._resolve_git("git+https://github.com/trusted/repo.git")
    argv = run.call_args.args[0]
    joined = " ".join(argv)
    assert "protocol.allow=never" in joined
    assert "protocol.https.allow=always" in joined
    assert "http.followRedirects=false" in joined
    assert "protocol.ssh.allow" not in joined and "protocol.file.allow" not in joined
    assert argv.index("clone") > argv.index("-c")


# ── 8. CGNAT / non-global egress ────────────────────────────────────────────

@pytest.mark.parametrize(
    "ip,blocked",
    [
        ("100.100.100.200", True),
        ("100.64.0.1", True),
        ("100.127.255.254", True),
        ("192.0.0.170", True),
        ("198.18.0.1", True),
        ("::ffff:127.0.0.1", True),
        ("::ffff:100.100.100.200", True),
        ("169.254.169.254", True),
        ("10.0.0.1", True),
        ("8.8.8.8", False),
        ("1.1.1.1", False),
        ("2606:4700:4700::1111", False),
    ],
)
def test_is_blocked_ip(ip, blocked):
    from app.core.trust.egress import is_blocked_ip

    assert is_blocked_ip(ipaddress.ip_address(ip)) is blocked
