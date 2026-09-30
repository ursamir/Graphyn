"""Security regressions: DNS-rebinding Host guard and config-file download denial."""
from __future__ import annotations

import pytest


@pytest.fixture
def no_token(monkeypatch):
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("GRAPHYN_ENV", "development")


class TestHostGuard:
    @pytest.mark.parametrize(
        "host",
        ["localhost:8001", "127.0.0.1:8001", "[::1]:8001", "192.168.1.20:3000",
         "graphyn-api:8001", "testserver", "app.localhost"],
    )
    def test_allowed_hosts(self, api_client, no_token, host):
        resp = api_client.get("/health", headers={"Host": host})
        assert resp.status_code == 200

    @pytest.mark.parametrize("host", ["evil.example", "evil.example:8001", "rebind.attacker.test"])
    def test_rebinding_host_rejected_without_token(self, api_client, no_token, host):
        resp = api_client.get("/api/v1/system/health", headers={"Host": host})
        assert resp.status_code == 403
        assert "GRAPHYN_ALLOWED_HOSTS" in resp.text

    def test_allowed_hosts_env(self, api_client, no_token, monkeypatch):
        monkeypatch.setenv("GRAPHYN_ALLOWED_HOSTS", "graphyn.lan, other.lan")
        assert api_client.get("/health", headers={"Host": "graphyn.lan:3000"}).status_code == 200
        assert api_client.get("/health", headers={"Host": "evil.example"}).status_code == 403

    def test_guard_off_when_token_set(self, api_client, monkeypatch):
        monkeypatch.setenv("GRAPHYN_API_TOKEN", "tok")
        resp = api_client.get("/health", headers={"Host": "graphyn.example.com"})
        assert resp.status_code == 200


def _jail(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    home = tmp_path / "graphyn-home"
    ws.mkdir()
    home.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    monkeypatch.setenv("GRAPHYN_HOME", str(home))
    return ws, home


class TestDownloadDenyConfig:
    @pytest.mark.parametrize(
        "rel,root",
        [
            ("webhooks.json", "ws"),
            ("schedules.json", "ws"),
            ("audit/events.json", "ws"),
            ("plugins/registry.json", "home"),
            ("credentials/meta.json", "home"),
            ("secrets/x.txt", "home"),
            (".env", "ws"),
            ("sub/.hidden/a.json", "ws"),
        ],
    )
    def test_config_files_denied(self, api_client, tmp_path, monkeypatch, rel, root):
        ws, home = _jail(tmp_path, monkeypatch)
        base = ws if root == "ws" else home
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"url": "https://hooks.example/T0K3N"}', encoding="utf-8")
        resp = api_client.get("/api/v1/outputs/file", params={"path": str(target)})
        assert resp.status_code in (403, 415)
        assert "T0K3N" not in resp.text

    def test_workspace_relative_webhooks_denied(self, api_client, tmp_path, monkeypatch):
        ws, _ = _jail(tmp_path, monkeypatch)
        (ws / "webhooks.json").write_text('{"url": "https://hooks.example/T0K3N"}', encoding="utf-8")
        resp = api_client.get("/api/v1/outputs/file", params={"path": "workspace/webhooks.json"})
        assert resp.status_code in (403, 404)
        assert "T0K3N" not in resp.text

    def test_normal_artifact_still_downloadable(self, api_client, tmp_path, monkeypatch):
        ws, _ = _jail(tmp_path, monkeypatch)
        out = ws / "artifacts" / "run1"
        out.mkdir(parents=True)
        (out / "metrics.json").write_text('{"acc": 1}', encoding="utf-8")
        resp = api_client.get("/api/v1/outputs/file", params={"path": str(out / "metrics.json")})
        assert resp.status_code == 200


def test_quality_check_route_rejects_bad_version(api_client, tmp_path, monkeypatch, no_token):
    _jail(tmp_path, monkeypatch)
    resp = api_client.post("/api/v1/projects/proj/quality-check", json={"version": "../../x"})
    assert resp.status_code == 422
