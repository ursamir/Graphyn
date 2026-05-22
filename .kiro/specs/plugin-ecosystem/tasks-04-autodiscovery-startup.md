# tasks-04 — AutoDiscovery Integration and Startup

## Overview

Update `AutoDiscovery.run()` to handle manifest-based plugin subdirectories, integrate `PluginManager.load_enabled_plugins()` into the startup sequence, and verify backward compatibility with legacy flat-file plugins.

## Tasks

- [x] 13. Update `AutoDiscovery.run()` to handle manifest-based plugin subdirectories (`app/core/nodes/discovery.py`)
  - After the existing flat `.py` file scan of `plugins_path`, add subdirectory iteration:
    - For each subdirectory in `plugins_path`:
      - If `plugin.toml` or `plugin.json` exists in the subdirectory → call `PluginLoader(self._registry).load(subdir)` in a try/except; log WARNING on failure
      - Otherwise → call `self._scan_directory(subdir, package_prefix=None)` (existing legacy behavior)
  - Add DEBUG log after successful legacy flat-file import: suggest adding `plugin.toml`
  - Do NOT change any other part of `AutoDiscovery` (steps 1, 2, 3 are unchanged)
  - _Requirements: req-09 §10.1, §10.2, §10.3_

- [x] 14. Integrate `PluginManager.load_enabled_plugins()` into startup (`app/core/registry_runtime.py` or equivalent)
  - Identify where `AutoDiscovery.run()` is called at startup (likely `app/core/registry_runtime.py` or `app/core/nodes/__init__.py`)
  - Add `PluginManager().load_enabled_plugins()` call BEFORE `AutoDiscovery.run()` is called
  - Wrap in try/except to ensure startup is not blocked by plugin load failures
  - _Requirements: req-03 §4.8_

- [x] 15. Write backward compatibility tests (`tests/test_plugin_backward_compat.py`)
  - [x]* 15.1 Test legacy flat `.py` plugin still registers correctly
    - Create a minimal `Node` subclass in a `.py` file in a temp plugins dir (no `plugin.toml`)
    - Run `AutoDiscovery.run()` with that plugins dir
    - Assert the node type is registered in `NodeRegistry`
    - _Requirements: req-09 §10.1_

  - [x]* 15.2 Test manifest-based plugin subdirectory is delegated to `PluginLoader`
    - Create a minimal plugin package (dir with `plugin.toml` + `.py` node file) in a temp plugins dir
    - Run `AutoDiscovery.run()` with that plugins dir
    - Assert the node type is registered in `NodeRegistry`
    - _Requirements: req-09 §10.2_

  - [x]* 15.3 Test legacy subdirectory (no `plugin.toml`) is scanned directly
    - Create a subdirectory with a `.py` node file but no `plugin.toml`
    - Run `AutoDiscovery.run()` with that plugins dir
    - Assert the node type is registered in `NodeRegistry`
    - _Requirements: req-09 §10.3_

  - [x]* 15.4 Test `GRAPHYN_PLUGINS_DIR` env var still controls the plugins directory
    - Set `GRAPHYN_PLUGINS_DIR` to a custom temp path
    - Place a legacy plugin `.py` file there
    - Run `AutoDiscovery.run()` without explicit `plugins_dir`
    - Assert the node type is registered
    - _Requirements: req-09 §10.4_

- [x] 16. Checkpoint — verify all existing tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions.
  - Ask the user if questions arise.
