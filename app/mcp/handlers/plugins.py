# app/mcp/handlers/plugins.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Plugin lifecycle MCP tools: install, list, enable/disable/uninstall.
Owns:             install_plugin_handler, list_plugins_handler, manage_plugin_handler
                  and their SCHEMA/DESCRIPTION constants.
Public Surface:   The three handler functions and schema/description constants.
Must NOT:         Contain plugin fetch/extract logic. Must not import from app.domain.
Dependencies:     BC3 (plugins.manager, plugins.errors), BC3 registry_runtime (lazy),
                  stdlib (typing).
Reason To Change: Plugin MCP tool schemas change, or PluginManager lifecycle API changes.
"""
from __future__ import annotations

from typing import Any


INSTALL_PLUGIN_DESCRIPTION = (
    "Install a plugin from a local path, git URL, HTTP archive, or index name. "
    "Honors GRAPHYN_PLUGIN_ALLOWED_SOURCES for remote sources. Reloads enabled "
    "plugins so list_nodes sees new node types in-process."
)

INSTALL_PLUGIN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "description": "Local path, git URL, HTTP archive URL, or plugin index name.",
        },
        "upgrade": {
            "type": "boolean",
            "description": "Replace an existing installation with the same name.",
            "default": False,
        },
        "expected_sha256": {
            "type": "string",
            "description": "Optional SHA-256 hex digest for HTTP archive sources.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["source"],
    "additionalProperties": False,
}

LIST_PLUGINS_DESCRIPTION = (
    "List installed plugins with enabled state and declared node_types."
)

LIST_PLUGINS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}

MANAGE_PLUGIN_DESCRIPTION = (
    "Enable, disable, or uninstall an installed plugin by name."
)

MANAGE_PLUGIN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["enable", "disable", "uninstall"],
            "description": "Lifecycle action to perform.",
        },
        "name": {
            "type": "string",
            "description": "Installed plugin name (manifest slug).",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["action", "name"],
    "additionalProperties": False,
}


def _node_types(record: Any) -> list[str]:
    manifest = getattr(record, "manifest", None) or {}
    raw = manifest.get("node_types") or []
    return [str(x) for x in raw]


def _error(exc: BaseException, error_type: str | None = None) -> dict[str, Any]:
    return {
        "error": True,
        "error_type": error_type or type(exc).__name__,
        "message": str(exc),
    }


def _manager():
    from app.core.plugins.manager import PluginManager

    return PluginManager()


def install_plugin_handler(arguments: dict[str, Any]) -> Any:
    """Install a plugin and reload so list_nodes sees new types."""
    from app.core.plugins.errors import PluginError

    source = arguments.get("source")
    if not source:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "Missing required argument 'source'.",
        }
    upgrade = bool(arguments.get("upgrade", False))
    expected_sha256 = arguments.get("expected_sha256") or None
    mgr = _manager()
    try:
        record = mgr.install(
            str(source),
            upgrade=upgrade,
            expected_sha256=expected_sha256,
        )
        mgr.load_enabled_plugins()
        return {
            "name": record.name,
            "version": record.version,
            "enabled": record.enabled,
            "node_types": _node_types(record),
        }
    except PluginError as exc:
        return _error(exc)
    except Exception as exc:
        return _error(exc, "plugin_install_error")


def list_plugins_handler(arguments: dict[str, Any]) -> Any:
    """Return installed plugins and their node types."""
    mgr = _manager()
    try:
        records = mgr.list_installed()
    except Exception as exc:
        return _error(exc, "store_error")
    plugins = [
        {
            "name": r.name,
            "version": r.version,
            "enabled": r.enabled,
            "node_types": _node_types(r),
        }
        for r in records
    ]
    return {"plugins": plugins}


def manage_plugin_handler(arguments: dict[str, Any]) -> Any:
    """Enable, disable, or uninstall a plugin by name."""
    from app.core.plugins.errors import PluginError

    action = (arguments.get("action") or "").strip().lower()
    name = arguments.get("name")
    if not name:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "Missing required argument 'name'.",
        }
    if action not in {"enable", "disable", "uninstall"}:
        return {
            "error": True,
            "error_type": "invalid_action",
            "message": "action must be enable, disable, or uninstall.",
            "action": action,
        }
    mgr = _manager()
    try:
        if action == "enable":
            record = mgr.enable(str(name))
            mgr.load_enabled_plugins()
            return {
                "ok": True,
                "action": action,
                "name": record.name,
                "enabled": record.enabled,
                "node_types": _node_types(record),
            }
        if action == "disable":
            record = mgr.disable(str(name))
            return {
                "ok": True,
                "action": action,
                "name": record.name,
                "enabled": record.enabled,
                "node_types": _node_types(record),
            }
        mgr.uninstall(str(name))
        return {"ok": True, "action": action, "name": str(name), "enabled": False}
    except PluginError as exc:
        return _error(exc)
    except Exception as exc:
        return _error(exc, "plugin_manage_error")
