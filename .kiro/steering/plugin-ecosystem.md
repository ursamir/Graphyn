---
inclusion: fileMatch
fileMatchPattern: "app/core/plugins/**"
---

# Plugin Ecosystem — Internals

All plugin lifecycle logic lives in `app/core/plugins/`. `PluginManager` is the single entry point — CLI, REST API, and SDK all delegate to it. Never call `PluginLoader`, `PluginStore`, or `PluginInstaller` directly from outside this package.

## Component Map

| Component | File | Responsibility |
|---|---|---|
| `PluginManager` | `manager.py` | Orchestrates install, uninstall, enable, disable, startup loading |
| `PluginInstaller` | `installer.py` | Resolves source strings (local path, git URL, HTTP archive, index name) |
| `PluginLoader` | `loader.py` | Validates manifest, checks compat/deps, imports entry points, registers node types |
| `PluginStore` | `store.py` | Persists `PluginRecord` objects as JSON under `workspace/plugins/` |
| `PluginIndexClient` | `index.py` | Fetches/searches remote plugin index (`GRAPHYN_PLUGIN_INDEX_URL`) |
| `PluginManifest` | `manifest.py` | Pydantic model for `plugin.toml`; `load_manifest(plugin_dir)` is the public loader |
| `DependencyChecker` | `dependencies.py` | Verifies PEP 508 dependency strings against current environment |

## `PluginLoader` Load Sequence

`PluginLoader.load(plugin_dir)` runs in order:

1. Parse manifest → `PluginManifest` (raises `PluginManifestError`)
2. Check `platform_version` specifier (raises `PluginCompatibilityError`)
3. Check `min_python` (raises `PluginCompatibilityError`)
4. Verify `dependencies` via `DependencyChecker` (raises `PluginDependencyError`)
5. Import each `entry_points` file via `AutoDiscovery._import_file` + `_process_module`
6. Return sorted list of newly registered `node_type` strings

Individual entry-point failures → WARNING + skip; remaining entry points still load.

## Key Invariants

- `AutoDiscovery` is not bypassed — `PluginLoader` uses it internally to register node types
- `unregister()` is called on disable/uninstall — removes every contributed `node_type` from registry
- Startup loading failures are WARNING, not fatal
- Remote installs (git+, http://) run via `BackgroundTasks`; local path installs are synchronous

## `PluginManager` Full Method Reference

| Method | Returns | Raises |
|---|---|---|
| `install(source, upgrade=False)` | `PluginRecord` | `PluginAlreadyInstalledError`, `PluginManifestError`, `PluginCompatibilityError`, `PluginDependencyError`, `PluginInstallError` |
| `uninstall(name)` | `None` | `PluginNotFoundError` |
| `enable(name)` | `PluginRecord` | `PluginNotFoundError` |
| `disable(name)` | `PluginRecord` | `PluginNotFoundError` |
| `list_installed()` | `list[PluginRecord]` | — |
| `get(name)` | `PluginRecord` | `PluginNotFoundError` |
| `load_enabled_plugins()` | `None` | — (failures logged, not raised) |

## Error Hierarchy

```
PluginError
├── PluginManifestError         # missing/malformed manifest
├── PluginCompatibilityError    # platform_version or min_python not satisfied
├── PluginDependencyError       # PEP 508 dependency not installed
├── PluginInstallError          # source fetch/extract failure
├── PluginNotFoundError         # name not in PluginStore (also KeyError)
├── PluginAlreadyInstalledError # install() without upgrade=True
└── PluginIndexError            # remote index fetch/parse failure
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHYN_PLUGINS_DIR` | `"plugins"` | Install directory |
| `GRAPHYN_PLUGIN_AUTO_INSTALL` | `""` | `"1"` or `"true"` to auto-install pip deps |
| `GRAPHYN_PLUGIN_INDEX_URL` | `""` | Remote index URL |
| `GRAPHYN_HOME` | `~/.graphyn/` | `PluginStore` writes to `{GRAPHYN_HOME}/plugins/` |
