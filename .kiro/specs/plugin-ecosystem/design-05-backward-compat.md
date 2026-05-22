# design-05 — Backward Compatibility and AutoDiscovery Integration

## Overview

This document details the minimal changes to `AutoDiscovery` that enable manifest-based plugins while preserving full backward compatibility with existing flat `.py` drop-in plugins.

## Updated `AutoDiscovery.run()` Logic

The only change to `AutoDiscovery` is in the `run()` method's plugin directory scanning step. The existing flat-file scan is preserved; a new branch handles subdirectories with `plugin.toml`.

```python
def run(
    self,
    nodes_dir: str | Path,
    plugins_dir: str | Path | None = None,
    models_dir: str | Path | None = None,
) -> None:
    # ... existing steps 1, 2, 3 unchanged ...

    # 4. Scan plugins_dir (updated)
    if plugins_dir is None:
        plugins_dir = os.environ.get("GRAPHYN_PLUGINS_DIR", "plugins")

    plugins_path = Path(plugins_dir)
    if plugins_path.exists() and plugins_path.is_dir():
        # 4a. Flat .py files (legacy — unchanged behavior)
        self._scan_directory(plugins_path, package_prefix=None)

        # 4b. Subdirectories
        for subdir in sorted(plugins_path.iterdir()):
            if not subdir.is_dir():
                continue
            if (subdir / "plugin.toml").exists() or (subdir / "plugin.json").exists():
                # Manifest-based plugin — delegate to PluginLoader
                try:
                    from app.core.plugins.loader import PluginLoader
                    loader = PluginLoader(self._registry)
                    loader.load(subdir)
                except Exception as exc:
                    log.warning(
                        "AutoDiscovery: failed to load manifest plugin '%s': %s",
                        subdir.name, exc
                    )
            else:
                # Legacy subdirectory — scan .py files directly
                self._scan_directory(subdir, package_prefix=None)
```

## Legacy Plugin Debug Hint

In `_scan_directory`, after successfully importing a plugin file, add a DEBUG log:

```python
# After successful import of a plugin file (package_prefix is None = plugin file)
if package_prefix is None:
    log.debug(
        "AutoDiscovery: loaded legacy plugin '%s'. "
        "Consider adding a plugin.toml manifest for dependency management and versioning.",
        py_file.name
    )
```

## Scan Behavior Summary

| Plugin directory contents | Behavior |
|---|---|
| `plugins/my_plugin.py` | Legacy flat file — imported directly (unchanged) |
| `plugins/my-plugin/plugin.toml` + `.py` files | Manifest plugin — delegated to `PluginLoader` |
| `plugins/old-package/` (no `plugin.toml`) | Legacy subdirectory — `.py` files scanned directly |

## `NodeRegistry.unregister()` Addition

```python
# app/core/nodes/registry.py — add this method

def unregister(self, node_type: str) -> None:
    """Remove a node type from the registry. No-op if not registered.

    Used by PluginManager when disabling or uninstalling a plugin.
    """
    self._classes.pop(node_type, None)
    self._metadata.pop(node_type, None)
```

## Startup Sequence

The full startup sequence with Phase 5 additions:

```
1. NodeRegistry.__init__()                    (existing)
2. PluginManager.load_enabled_plugins()       (NEW — loads managed plugins from PluginStore)
3. AutoDiscovery.run(nodes_dir, plugins_dir)  (existing + updated plugin dir scan)
   3a. Scan app/core/nodes/ (built-in nodes)
   3b. Scan app/core/nodes/audio/, ml/ (category subdirs)
   3c. Scan app/models/ (PortDataType subclasses)
   3d. Scan plugins/ flat .py files (legacy)
   3e. Scan plugins/ subdirs:
       - with plugin.toml → PluginLoader.load() (NEW)
       - without plugin.toml → _scan_directory() (existing)
```

Step 2 runs before step 3 to ensure that managed plugins (which may have been installed to the plugins directory) are loaded with full manifest validation before `AutoDiscovery` scans the directory. This prevents double-registration: `PluginLoader.load()` registers the node types, and `AutoDiscovery` step 3e will call `PluginLoader.load()` again for the same directory — but `NodeRegistry.register()` already handles re-registration gracefully (the `if existing is not cls: raise` check in `_register_node` means re-importing the same class is a no-op).

## Design Decisions

1. **Minimal change to `AutoDiscovery`**: Only the plugin directory scanning step changes. All other steps (built-in nodes, category subdirs, models) are unchanged.

2. **`PluginLoader` is called from `AutoDiscovery`**: This means manifest plugins discovered by `AutoDiscovery` go through the same validation path as plugins installed via `PluginManager`. There is no separate "unmanaged manifest plugin" concept.

3. **Double-registration is safe**: If `PluginManager.load_enabled_plugins()` already loaded a plugin, `AutoDiscovery` will call `PluginLoader.load()` again for the same directory. The second call will re-import the same module and try to register the same classes. `NodeRegistry._register_node()` handles this: `if existing is not cls: raise` — but since it's the same class object (Python module cache), `existing is cls` is True and the re-registration is silently skipped.
