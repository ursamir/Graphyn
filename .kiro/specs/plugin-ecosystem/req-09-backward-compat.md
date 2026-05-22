# req-09 — Backward Compatibility

## Introduction

The existing flat `.py` drop-in plugin mechanism must continue to work without any changes to existing plugin files. Phase 5 adds manifest-based plugins as a superset of the existing behavior, not a replacement.

## Requirement 10: Backward Compatibility

**User Story:** As an existing plugin author, I want my flat `.py` drop-in plugins to continue working without modification, so that I do not need to migrate existing plugins to use the new manifest system.

### Acceptance Criteria

1. WHEN `AutoDiscovery` scans the plugins directory and encounters a `.py` file with no accompanying `plugin.toml` in the same directory or parent directory, THE AutoDiscovery SHALL import and register the file using the existing flat-file mechanism unchanged.
2. WHEN `AutoDiscovery` scans the plugins directory and encounters a subdirectory containing a `plugin.toml`, THE AutoDiscovery SHALL delegate that subdirectory to `PluginLoader` instead of scanning it directly.
3. WHEN `AutoDiscovery` scans the plugins directory and encounters a subdirectory without a `plugin.toml`, THE AutoDiscovery SHALL scan the subdirectory for `.py` files using the existing mechanism (legacy package mode).
4. THE `GRAPHYN_PLUGINS_DIR` environment variable SHALL continue to control the root plugins directory for both legacy and manifest-based plugins.
5. WHEN a legacy plugin file is loaded, THE AutoDiscovery SHALL log a DEBUG-level message suggesting the author add a `plugin.toml` manifest.
6. THE existing `plugin-development.md` steering file template SHALL remain valid and functional for legacy plugins.

## Scan Logic (Updated `AutoDiscovery.run()`)

```
plugins_dir/
├── legacy_plugin.py          → flat file: import directly (existing behavior)
├── another_legacy.py         → flat file: import directly (existing behavior)
├── my-plugin/                → subdirectory with plugin.toml: delegate to PluginLoader
│   ├── plugin.toml
│   └── my_plugin.py
└── old-package/              → subdirectory without plugin.toml: scan .py files (legacy)
    ├── node_a.py
    └── node_b.py
```

The change to `AutoDiscovery.run()` is minimal: after scanning flat `.py` files, iterate subdirectories. If a subdirectory has `plugin.toml`, call `PluginLoader.load(subdir)`. Otherwise, call `self._scan_directory(subdir, package_prefix=None)` as before.

## Migration Path

Plugin authors who want to adopt manifests can do so incrementally:
1. Create a `plugin.toml` in the same directory as their `.py` file (or move the `.py` into a subdirectory).
2. Add `entry_points = ["my_plugin.py"]` to the manifest.
3. The platform will now use `PluginLoader` for that plugin.

No changes to the `.py` file itself are required.
