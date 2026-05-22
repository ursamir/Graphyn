# unit_test/api/test_plugins_router.py
"""Tests for /api/v1/plugins router."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.core.plugins.errors import PluginNotFoundError


def _make_plugin_record(name: str = "my-plugin", version: str = "1.0.0", enabled: bool = True):
    """Return a minimal mock PluginRecord."""
    record = MagicMock()
    record.name = name
    record.version = version
    record.enabled = enabled
    record.model_dump.return_value = {
        "name": name,
        "version": version,
        "enabled": enabled,
    }
    return record


def _make_manager(records=None, plugin_name: str = "my-plugin"):
    """Return a mock PluginManager."""
    manager = MagicMock()
    manager.list_installed.return_value = records or []
    record = _make_plugin_record(plugin_name)
    manager.install.return_value = record
    manager.get.return_value = record
    manager.enable.return_value = record
    manager.disable.return_value = _make_plugin_record(plugin_name, enabled=False)
    manager.uninstall.return_value = None
    return manager


class TestListPlugins:
    def test_returns_200_with_list(self, api_client):
        """GET /api/v1/plugins returns 200 with a list of plugins."""
        manager = _make_manager()
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.get("/api/v1/plugins")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_returns_empty_list_when_no_plugins(self, api_client):
        """GET /api/v1/plugins returns [] when no plugins are installed."""
        manager = _make_manager(records=[])
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.get("/api/v1/plugins")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_plugin_records(self, api_client):
        """GET /api/v1/plugins returns serialized PluginRecord objects."""
        record = _make_plugin_record("audio-plugin")
        manager = _make_manager(records=[record])
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.get("/api/v1/plugins")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "audio-plugin"


class TestInstallPlugin:
    def test_install_local_plugin_returns_200(self, api_client):
        """POST /api/v1/plugins/install installs a local plugin and returns 200."""
        manager = _make_manager("my-plugin")
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.post(
                "/api/v1/plugins/install",
                json={"source": "my-plugin==1.0.0", "upgrade": False},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "name" in body or "status" in body

    def test_install_remote_plugin_returns_installing(self, api_client):
        """POST /api/v1/plugins/install with remote source returns installing status."""
        manager = _make_manager()
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.post(
                "/api/v1/plugins/install",
                json={"source": "https://github.com/example/plugin.git", "upgrade": False},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "installing"


class TestGetPlugin:
    def test_unknown_plugin_returns_404(self, api_client):
        """GET /api/v1/plugins/{name} returns 404 for unknown plugin."""
        manager = _make_manager()
        manager.get.side_effect = PluginNotFoundError("not found")
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.get("/api/v1/plugins/nonexistent-plugin")
        assert resp.status_code == 404

    def test_known_plugin_returns_200(self, api_client):
        """GET /api/v1/plugins/{name} returns 200 for installed plugin."""
        manager = _make_manager("my-plugin")
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.get("/api/v1/plugins/my-plugin")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "my-plugin"


class TestEnablePlugin:
    def test_enable_known_plugin_returns_200(self, api_client):
        """POST /api/v1/plugins/{name}/enable returns 200 for installed plugin."""
        manager = _make_manager("my-plugin")
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.post("/api/v1/plugins/my-plugin/enable")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "my-plugin"
        assert body["enabled"] is True

    def test_enable_unknown_plugin_returns_404(self, api_client):
        """POST /api/v1/plugins/{name}/enable returns 404 for unknown plugin."""
        manager = _make_manager()
        manager.enable.side_effect = PluginNotFoundError("not found")
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.post("/api/v1/plugins/nonexistent/enable")
        assert resp.status_code == 404


class TestDisablePlugin:
    def test_disable_known_plugin_returns_200(self, api_client):
        """POST /api/v1/plugins/{name}/disable returns 200 for installed plugin."""
        manager = _make_manager("my-plugin")
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.post("/api/v1/plugins/my-plugin/disable")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "my-plugin"
        assert body["enabled"] is False

    def test_disable_unknown_plugin_returns_404(self, api_client):
        """POST /api/v1/plugins/{name}/disable returns 404 for unknown plugin."""
        manager = _make_manager()
        manager.disable.side_effect = PluginNotFoundError("not found")
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.post("/api/v1/plugins/nonexistent/disable")
        assert resp.status_code == 404


class TestDeletePlugin:
    def test_delete_unknown_plugin_returns_404(self, api_client):
        """DELETE /api/v1/plugins/{name} returns 404 for unknown plugin."""
        manager = _make_manager()
        manager.uninstall.side_effect = PluginNotFoundError("not found")
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.delete("/api/v1/plugins/nonexistent-plugin")
        assert resp.status_code == 404

    def test_delete_known_plugin_returns_200(self, api_client):
        """DELETE /api/v1/plugins/{name} returns 200 for installed plugin."""
        manager = _make_manager("my-plugin")
        with patch("app.core.plugins.manager.PluginManager", return_value=manager):
            resp = api_client.delete("/api/v1/plugins/my-plugin")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "my-plugin"
        assert body["status"] == "uninstalled"
