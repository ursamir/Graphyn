# tasks-02 — PluginStore, PluginLoader, and NodeRegistry Extension

## Overview

Implement `PluginStore` (persistence), `PluginLoader` (manifest-based plugin loading), and the `NodeRegistry.unregister()` extension. These depend on the foundation from tasks-01.

## Tasks

- [x] 5. Add `NodeRegistry.unregister()` (`app/core/nodes/registry.py`)
  - Add `unregister(self, node_type: str) -> None` method
  - Implementation: `self._classes.pop(node_type, None)` and `self._metadata.pop(node_type, None)`
  - No-op if `node_type` is not registered
  - _Requirements: req-03 §4.4, §4.6_

- [x] 6. Implement `PluginStore` and `PluginRecord` (`app/core/plugins/store.py`)
  - [x] 6.1 Define `PluginRecord(BaseModel, frozen=True)` with fields: `name`, `version`, `source`, `install_path`, `enabled`, `installed_at` (ISO 8601 string), `manifest` (dict)
    - _Requirements: req-03 §4.1, §4.2_

  - [x] 6.2 Implement `PluginStore.__init__()` and `_load()` / `_save()`
    - `__init__(base_dir=None)`: reads `GRAPHYN_PROJECT_DIR`, sets `self.base = Path(...) / "plugins"`, creates dirs, initializes `self._lock = threading.Lock()`
    - `_load() -> dict`: reads `registry.json`; returns `{}` on missing or corrupt file (log WARNING)
    - `_save(data: dict)`: atomic write via `.tmp` + `rename()`
    - _Requirements: req-03 §4.1, §4.10_

  - [x] 6.3 Implement `PluginStore.get()`, `list()`, `save()`, `delete()`, `update_enabled()`
    - `get(name) -> PluginRecord`: raises `PluginNotFoundError` if not in registry
    - `list() -> list[PluginRecord]`: returns all records sorted by name
    - `save(record)`: upsert — write or overwrite the record for `record.name`
    - `delete(name)`: raises `PluginNotFoundError` if not found; removes entry and saves
    - `update_enabled(name, enabled) -> PluginRecord`: raises `PluginNotFoundError` if not found; updates `enabled` field and saves
    - All methods acquire `self._lock` for read-modify-write operations
    - _Requirements: req-03 §4.1, §4.3, §4.4, §4.5, §4.6, §4.10_

  - [x]* 6.4 Write unit tests for `PluginStore`
    - Create `tests/test_plugin_store.py`
    - Test `save()` creates `registry.json` with correct content
    - Test `get()` returns correct `PluginRecord`
    - Test `get()` raises `PluginNotFoundError` for unknown name
    - Test `list()` returns all saved records
    - Test `delete()` removes the record
    - Test `delete()` raises `PluginNotFoundError` for unknown name
    - Test `update_enabled(name, False)` sets `enabled=False`
    - Test `update_enabled(name, True)` sets `enabled=True`
    - Test corrupt `registry.json` is handled gracefully (treated as empty)
    - Test `save()` is idempotent (saving same record twice → one entry)
    - Use `tmp_path` fixture and `monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))`
    - _Requirements: req-03 §4.1, §4.2, §4.10_

- [x] 7. Implement `PluginLoader` (`app/core/plugins/loader.py`)
  - [x] 7.1 Implement `PluginLoader.__init__()` and `load(plugin_dir) -> list[str]`
    - `__init__(registry)`: store registry reference
    - `load(plugin_dir)`:
      1. Call `load_manifest(plugin_dir)` — raises `PluginManifestError` on failure
      2. Call `_check_platform_compat(manifest)` — raises `PluginCompatibilityError` if version not in specifier
      3. Call `_check_python_compat(manifest)` — raises `PluginCompatibilityError` if Python version too old
      4. Call `DependencyChecker().check(manifest.dependencies)` — raises `PluginDependencyError` if unsatisfied
      5. Call `_import_entry_points(plugin_dir, manifest)` — returns list of new node_types
      6. Log INFO: plugin name, version, node count
      7. Return list of registered node_types
    - _Requirements: req-02 §2.1, §2.2, §2.3, §2.7, §2.8_

  - [x] 7.2 Implement `_check_platform_compat()` and `_check_python_compat()`
    - `_check_platform_compat(manifest)`: read `PLATFORM_VERSION` constant; check `Version(PLATFORM_VERSION) in SpecifierSet(manifest.platform_version)`; raise `PluginCompatibilityError` with plugin name, required constraint, actual version
    - `_check_python_compat(manifest)`: if `manifest.min_python` is set, check current Python version; raise `PluginCompatibilityError` with required and actual versions
    - _Requirements: req-02 §2.2, §2.3_

  - [x] 7.3 Implement `_import_entry_points()`
    - For each `ep` in `manifest.entry_points`: call `AutoDiscovery._import_file(plugin_dir / ep, package_prefix=None)` then `AutoDiscovery._process_module(module)`
    - Catch and log WARNING for individual entry point failures (do not abort the whole plugin)
    - Return list of node_types newly added to registry (set difference before/after)
    - _Requirements: req-02 §2.8_

  - [x]* 7.4 Write unit tests for `PluginLoader`
    - Create `tests/test_plugin_loader.py`
    - Test valid manifest + compatible platform → nodes registered, returns node_type list
    - Test incompatible platform version → `PluginCompatibilityError` with correct message
    - Test incompatible Python version → `PluginCompatibilityError`
    - Test unsatisfied dependency → `PluginDependencyError`
    - Test missing manifest → `PluginManifestError`
    - Test entry point import failure → WARNING logged, other entry points still loaded
    - Test legacy plugin dir (no manifest) → `PluginManifestError` (caller handles this)
    - Use `tmp_path` to create minimal plugin packages with real `.py` node files
    - Mock `DependencyChecker.check` to avoid real pip checks
    - _Requirements: req-02 §2.1–§2.9_

- [x] 8. Checkpoint — verify all existing tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions.
  - Ask the user if questions arise.
