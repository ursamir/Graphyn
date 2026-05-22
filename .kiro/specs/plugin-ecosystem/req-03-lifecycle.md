# req-03 — Plugin Lifecycle

## Introduction

The plugin lifecycle covers the four operations that change a plugin's state: install, enable, disable, and uninstall. State is persisted in `workspace/plugins/registry.json` via `PluginStore`. `PluginManager` is the single entry point for all lifecycle operations and is the component that CLI, REST API, and SDK all delegate to.

## Glossary

- **PluginRecord** — Pydantic model representing the persisted state of an installed plugin.
- **PluginStore** — On-disk persistence layer for `PluginRecord` objects.
- **PluginManager** — Orchestrates lifecycle operations; delegates to `PluginStore`, `PluginLoader`, and `PluginInstaller`.
- **PluginAlreadyInstalledError** — Raised when installing a plugin whose name is already in `PluginStore` and `upgrade=False`.
- **PluginNotFoundError** — Raised when an operation targets a plugin name not in `PluginStore`.

## Requirement 4: Plugin Lifecycle

**User Story:** As a platform operator, I want to install, enable, disable, and uninstall plugins through a managed lifecycle, so that I can control which plugins are active without restarting the server.

### Acceptance Criteria

1. THE PluginStore SHALL persist plugin state in `workspace/plugins/registry.json` as a JSON object mapping plugin name to `PluginRecord`.
2. THE PluginRecord SHALL contain the following fields: `name`, `version`, `source` (install source URL or path), `install_path` (absolute path to the installed plugin directory), `enabled` (boolean), `installed_at` (ISO 8601 timestamp), `manifest` (the full parsed manifest as a dict).
3. WHEN a plugin is installed, THE PluginManager SHALL write a `PluginRecord` to `PluginStore` with `enabled=true`.
4. WHEN a plugin is disabled, THE PluginManager SHALL update the `PluginRecord` in `PluginStore` to `enabled=false` and unload the plugin's node types from `NodeRegistry`.
5. WHEN a plugin is enabled, THE PluginManager SHALL update the `PluginRecord` in `PluginStore` to `enabled=true` and reload the plugin's node types into `NodeRegistry`.
6. WHEN a plugin is uninstalled, THE PluginManager SHALL remove the `PluginRecord` from `PluginStore`, unload the plugin's node types from `NodeRegistry`, and delete the plugin directory from disk.
7. WHEN a plugin is uninstalled and its node types are referenced in a loaded `GraphIR`, THE PluginManager SHALL log a WARNING identifying the affected node types but SHALL proceed with uninstallation.
8. WHEN the platform starts, THE PluginManager SHALL load all plugins with `enabled=true` from `PluginStore` before `AutoDiscovery` scans the plugins directory.
9. WHEN a plugin with the same name is already installed, THE PluginManager SHALL raise a `PluginAlreadyInstalledError` unless the `--upgrade` flag is specified, in which case it SHALL replace the existing installation.
10. THE PluginStore SHALL use a threading lock for all read-modify-write operations on `registry.json`.

## PluginRecord Schema

```python
class PluginRecord(BaseModel, frozen=True):
    name: str
    version: str
    source: str
    install_path: str
    enabled: bool
    installed_at: str   # ISO 8601
    manifest: dict      # raw manifest dict for forward compatibility
```

## Unload Mechanism

When disabling or uninstalling a plugin, the `PluginManager` must remove the plugin's node types from `NodeRegistry`. Since `NodeRegistry` does not currently have an `unregister()` method, Phase 5 adds `NodeRegistry.unregister(node_type: str) -> None` that removes the entry from `_classes` and `_metadata`. This is the only change to `NodeRegistry`.

## Startup Integration

`PluginManager.load_enabled_plugins()` is called from `app/core/registry_runtime.py` (or equivalent startup hook) after `NodeRegistry` is initialized but before `AutoDiscovery` runs. This ensures that managed plugins are loaded in the correct order and that their node types are available when `AutoDiscovery` scans for legacy plugins.

## File Locations

- `app/core/plugins/store.py` — `PluginStore`, `PluginRecord`
- `app/core/plugins/manager.py` — `PluginManager`
- `app/core/plugins/loader.py` — `PluginLoader`
- `app/core/plugins/errors.py` — All plugin exception classes
