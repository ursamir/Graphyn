# Implementation Plan: Plugin Ecosystem (Phase 5)

## Overview

Implement the Phase 5 plugin ecosystem as a set of additive components in `app/core/plugins/`. No existing file is removed; no existing public API signature changes. The regression baseline is all existing tests — verified after each task group.

## Task Groups and Dependency Graph

```
Group A: Foundation (errors, manifest, dependencies)    (no dependencies)
Group B: PluginStore + PluginLoader                     (depends on A)
Group C: PluginManager + PluginInstaller + IndexClient  (depends on A, B)
Group D: AutoDiscovery integration + startup            (depends on B, C)
Group E: CLI + REST API + SDK                           (depends on C)
Group F: Property-Based Tests                           (depends on A, B, C, D, E)
Group G: Documentation                                  (depends on F)
```

Groups A can start immediately. B depends on A. C depends on A and B. D and E can be implemented in parallel after C. F depends on all implementation groups. G is last.

---

## Tasks

- [x] 1. Create `app/core/plugins/` package and error classes
  - Create `app/core/plugins/__init__.py`
  - Create `app/core/plugins/errors.py` with full error hierarchy: `PluginError`, `PluginManifestError`, `PluginCompatibilityError`, `PluginDependencyError`, `PluginInstallError`, `PluginNotFoundError`, `PluginAlreadyInstalledError`, `PluginIndexError`
  - _Requirements: req-01 §1.4, req-02 §2.2, req-03 §3.2, req-04 §5.6, req-05 §6.8_

- [x] 2. Implement `PluginManifest` and `load_manifest()` (`app/core/plugins/manifest.py`)
  - [x] 2.1 Define `PluginManifest` Pydantic model with all required and optional fields and field validators
    - Required: `name` (slug `^[a-z][a-z0-9_-]*$`), `version` (PEP 440), `description`, `author`, `platform_version` (PEP 440 specifier), `entry_points` (list[str], min 1)
    - Optional: `tags=[]`, `dependencies=[]`, `homepage=None`, `license=None`, `min_python=None`
    - Validators: slug regex, `packaging.version.Version`, `packaging.specifiers.SpecifierSet`, `packaging.requirements.Requirement` per dep, `.py` suffix per entry point
    - _Requirements: req-01 §1.1, §1.2, §1.7, §1.8, §1.9, §1.10_

  - [x] 2.2 Implement `load_manifest(plugin_dir: Path) -> PluginManifest`
    - Try `plugin.toml` first (using `tomllib`/`tomli`), then `plugin.json`; raise `PluginManifestError` if neither exists
    - Support both `[plugin]` section and flat top-level in TOML
    - Wrap `pydantic.ValidationError` in `PluginManifestError`
    - _Requirements: req-01 §1.3, §1.4, §1.5, §1.6_

  - [x]* 2.3 Write unit tests for `PluginManifest` and `load_manifest()`
    - `tests/test_plugin_manifest.py` — valid TOML, valid JSON, precedence, all invalid field cases
    - _Requirements: req-01 §1.1–§1.10_

- [x] 3. Implement `DependencyChecker` (`app/core/plugins/dependencies.py`)
  - [x] 3.1 Implement `DependencyChecker.check(dependencies: list[str]) -> None`
    - Skip if empty; validate PEP 508; check all deps with `importlib.metadata`; collect ALL failures; raise `PluginDependencyError` with full list
    - _Requirements: req-02 §3.1, §3.2, §3.6, §3.7, §3.8_

  - [x] 3.2 Implement auto-install mode (`GRAPHYN_PLUGIN_AUTO_INSTALL=1`)
    - When enabled: run `pip install` for unsatisfied deps; log success; raise on pip failure
    - _Requirements: req-02 §3.3, §3.4, §3.5_

  - [x]* 3.3 Write unit tests for `DependencyChecker`
    - `tests/test_plugin_dependencies.py` — satisfied, unsatisfied, multiple failures, auto-install success/failure
    - _Requirements: req-02 §3.1–§3.8_

- [x] 4. Checkpoint — verify all existing tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions.
  - Ask the user if questions arise.

- [x] 5. Add `NodeRegistry.unregister()` (`app/core/nodes/registry.py`)
  - Add `unregister(self, node_type: str) -> None`: `self._classes.pop(node_type, None)` and `self._metadata.pop(node_type, None)`
  - _Requirements: req-03 §4.4, §4.6_

- [x] 6. Implement `PluginStore` and `PluginRecord` (`app/core/plugins/store.py`)
  - [x] 6.1 Define `PluginRecord(BaseModel, frozen=True)` with fields: `name`, `version`, `source`, `install_path`, `enabled`, `installed_at`, `manifest`
    - _Requirements: req-03 §4.1, §4.2_

  - [x] 6.2 Implement `PluginStore.__init__()`, `_load()`, `_save()` with atomic writes and threading lock
    - _Requirements: req-03 §4.1, §4.10_

  - [x] 6.3 Implement `PluginStore.get()`, `list()`, `save()`, `delete()`, `update_enabled()`
    - All read-modify-write operations acquire `self._lock`
    - _Requirements: req-03 §4.1, §4.3–§4.6, §4.10_

  - [x]* 6.4 Write unit tests for `PluginStore`
    - `tests/test_plugin_store.py` — CRUD, thread safety, corrupt file handling
    - _Requirements: req-03 §4.1, §4.2, §4.10_

- [x] 7. Implement `PluginLoader` (`app/core/plugins/loader.py`)
  - [x] 7.1 Implement `PluginLoader.load(plugin_dir) -> list[str]`
    - Steps: parse manifest → check platform compat → check Python compat → check deps → import entry points → log → return node_types
    - _Requirements: req-02 §2.1–§2.9_

  - [x] 7.2 Implement `_check_platform_compat()` and `_check_python_compat()`
    - Use `packaging.version.Version` and `packaging.specifiers.SpecifierSet`
    - Raise `PluginCompatibilityError` with plugin name, required constraint, actual version
    - _Requirements: req-02 §2.2, §2.3_

  - [x] 7.3 Implement `_import_entry_points()` delegating to `AutoDiscovery`
    - Log WARNING for individual entry point failures; continue loading others
    - Return list of newly registered node_types (set difference)
    - _Requirements: req-02 §2.8_

  - [x]* 7.4 Write unit tests for `PluginLoader`
    - `tests/test_plugin_loader.py` — valid load, incompatible platform, incompatible Python, unsatisfied dep, missing manifest, entry point failure
    - _Requirements: req-02 §2.1–§2.9_

- [x] 8. Checkpoint — verify all existing tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions.
  - Ask the user if questions arise.

- [x] 9. Implement `PluginInstaller` (`app/core/plugins/installer.py`)
  - [x] 9.1 Implement source string routing in `resolve(source, version_constraint=None) -> Path`
    - Route: `git+`/`.git` → git clone; `http(s)://...zip/tar.gz` → HTTP archive; local dir → copy; local archive → extract; plain name → index lookup
    - _Requirements: req-04 §5.1–§5.5, §5.10_

  - [x] 9.2 Implement `_resolve_git()`, `_resolve_http_archive()`, `_resolve_local_dir()`, `_resolve_local_archive()`
    - Use `subprocess.run` for git, `httpx.get` for HTTP, `zipfile`/`tarfile` for archives
    - Raise `PluginInstallError` on all failures; clean up temp files on both success and failure
    - _Requirements: req-04 §5.1, §5.2, §5.4, §5.5, §5.6, §5.7, §5.9_

  - [x] 9.3 Implement `_find_manifest_dir()`, `_verify_checksum()`, `_parse_name_version()`
    - Search 2 levels deep for `plugin.toml`; raise `PluginInstallError` if not found
    - Verify `sha256:` checksum; raise `PluginInstallError` on mismatch
    - _Requirements: req-04 §5.8, req-05 §6.6_

  - [x]* 9.4 Write unit tests for `PluginInstaller`
    - `tests/test_plugin_installer.py` — source routing, git failure, HTTP 404, no manifest, checksum mismatch, temp cleanup
    - _Requirements: req-04 §5.1–§5.10_

- [x] 10. Implement `PluginIndexClient` (`app/core/plugins/index.py`)
  - [x] 10.1 Define `PluginIndexEntry` and implement `fetch()`, `search()`, `lookup()`
    - In-memory class-level cache; remote via `GRAPHYN_PLUGIN_INDEX_URL`; local fallback at `workspace/plugins/index.json`
    - `search()`: case-insensitive match in name/description/tags
    - `lookup()`: filter by name and optional version; return highest version; raise `PluginNotFoundError`
    - _Requirements: req-05 §6.1–§6.9_

  - [x] 10.2 Implement remote and local fetch paths with error handling
    - _Requirements: req-05 §6.2, §6.3, §6.4, §6.7, §6.8_

  - [x]* 10.3 Write unit tests for `PluginIndexClient`
    - `tests/test_plugin_index.py` — remote fetch, local fetch, no source, caching, search, lookup, errors
    - _Requirements: req-05 §6.1–§6.9_

- [x] 11. Implement `PluginManager` (`app/core/plugins/manager.py`)
  - [x] 11.1 Implement `install()` and `uninstall()`
    - `install()`: resolve → parse manifest → check duplicate → (upgrade: uninstall first) → copy → load → save record → return
    - `uninstall()`: get record → unload node types → delete record → rmtree
    - _Requirements: req-03 §4.3, §4.6, §4.9_

  - [x] 11.2 Implement `enable()`, `disable()`, `list_installed()`, `get()`, `load_enabled_plugins()`
    - `enable()`: load plugin if not enabled; update store
    - `disable()`: unload node types if enabled; update store
    - `load_enabled_plugins()`: iterate store; load each enabled plugin; log WARNING on failure
    - _Requirements: req-03 §4.4, §4.5, §4.8, req-08 §9.2–§9.8_

  - [x] 11.3 Implement `_unload_node_types(record)`
    - Identify node types by `cls.__module__` matching; call `registry.unregister()` for each
    - _Requirements: req-03 §4.4, §4.6, §4.7_

  - [x]* 11.4 Write unit tests for `PluginManager`
    - `tests/test_plugin_manager.py` — full lifecycle: install, duplicate, upgrade, uninstall, enable, disable, list, get, load_enabled_plugins
    - _Requirements: req-03 §4.1–§4.10, req-08 §9.2–§9.8_

- [x] 12. Checkpoint — verify all existing tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions.
  - Ask the user if questions arise.

- [x] 13. Update `AutoDiscovery.run()` for manifest-based subdirectories (`app/core/nodes/discovery.py`)
  - After flat `.py` scan: iterate subdirs; if `plugin.toml`/`plugin.json` present → `PluginLoader.load()`; else → `_scan_directory()` (legacy)
  - Add DEBUG log for legacy flat-file plugins suggesting `plugin.toml`
  - _Requirements: req-09 §10.1, §10.2, §10.3_

- [x] 14. Integrate `PluginManager.load_enabled_plugins()` into startup
  - Add call BEFORE `AutoDiscovery.run()` in the startup sequence
  - Wrap in try/except to prevent startup failure
  - _Requirements: req-03 §4.8_

- [x] 15. Write backward compatibility tests (`tests/test_plugin_backward_compat.py`)
  - [x]* 15.1 Test legacy flat `.py` plugin still registers correctly
    - _Requirements: req-09 §10.1_
  - [x]* 15.2 Test manifest-based plugin subdirectory is delegated to `PluginLoader`
    - _Requirements: req-09 §10.2_
  - [x]* 15.3 Test legacy subdirectory (no `plugin.toml`) is scanned directly
    - _Requirements: req-09 §10.3_
  - [x]* 15.4 Test `GRAPHYN_PLUGINS_DIR` env var still controls the plugins directory
    - _Requirements: req-09 §10.4_

- [x] 16. Checkpoint — verify all existing tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions.
  - Ask the user if questions arise.

- [x] 17. Implement `audiobuilder plugin` CLI subcommand group (`app/cli/main.py`)
  - [x] 17.1 Implement `cmd_plugin_install`, `cmd_plugin_list`, `cmd_plugin_enable`, `cmd_plugin_disable`, `cmd_plugin_remove`, `cmd_plugin_search`, `cmd_plugin_info`
    - All delegate to `PluginManager`; catch `PluginError` subclasses; print user-friendly messages; `sys.exit(1)` on error
    - _Requirements: req-06 §7.1–§7.11_

  - [x] 17.2 Register `plugin` subparser in `build_parser()`
    - Sub-subcommands: `install` (source, --upgrade), `list` (--enabled), `enable` (name), `disable` (name), `remove` (name), `search` (query), `info` (name)
    - _Requirements: req-06 §7.1_

  - [x]* 17.3 Write unit tests for CLI plugin subcommand
    - `tests/test_plugins_cli.py` — all 7 subcommands, error cases, table output
    - _Requirements: req-06 §7.1–§7.11_

- [x] 18. Implement REST API `/api/v1/plugins/` (`app/api/routers/plugins.py`)
  - [x] 18.1 Create `plugins.py` router with all 7 endpoints
    - Error mapping: `PluginNotFoundError` → 404, `PluginAlreadyInstalledError` → 409, `PluginCompatibilityError`/`PluginDependencyError` → 422, `PluginInstallError`/`PluginIndexError` → 502
    - Async install for remote sources via `BackgroundTasks`
    - _Requirements: req-07 §8.1–§8.10_

  - [x] 18.2 Register `plugins_router` in `app/api/main.py`
    - _Requirements: req-07 §8.1_

  - [x]* 18.3 Write unit tests for plugins REST API
    - `tests/test_plugins_api.py` — all endpoints, error codes, async install
    - _Requirements: req-07 §8.1–§8.10_

- [x] 19. Add `Pipeline.install_plugin()` to SDK (`app/core/sdk.py`)
  - `install_plugin(self, source, upgrade=False) -> PluginRecord`: delegates to `PluginManager().install()`
  - _Requirements: req-08 §9.9_

  - [x]* 19.1 Write unit test for `Pipeline.install_plugin()`
    - _Requirements: req-08 §9.9_

- [x] 20. Checkpoint — verify all existing tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions.
  - Ask the user if questions arise.

- [x] 21. Write property-based tests (`tests/test_plugin_properties.py`)
  - [x]* 21.1 Write Property 1: Manifest Round-Trip
    - **Property 1: Manifest round-trip** — for any valid PluginManifest, serialize to TOML and parse back → equal
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 1: Manifest round-trip`
    - **Validates: Requirements 1.1, 1.3**

  - [x]* 21.2 Write Property 2: Invalid Manifest Always Rejected
    - **Property 2: Invalid manifest always rejected** — for any manifest with at least one invalid field, parsing raises PluginManifestError
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 2: Invalid manifest always rejected`
    - **Validates: Requirements 1.4, 1.5, 1.7, 1.8, 1.9, 3.8**

  - [x]* 21.3 Write Property 3: Platform Version Compatibility Correctness
    - **Property 3: Platform version compatibility correctness** — for any (version, specifier) pair, PluginLoader accepts iff Version(v) in SpecifierSet(c)
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 3: Platform version compatibility correctness`
    - **Validates: Requirements 2.2**

  - [x]* 21.4 Write Property 4: Dependency Reporting Completeness
    - **Property 4: Dependency reporting completeness** — for any set of unsatisfied deps, DependencyChecker reports exactly all of them
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 4: Dependency reporting completeness`
    - **Validates: Requirements 3.1, 3.2**

  - [x]* 21.5 Write Property 5: PluginStore Round-Trip
    - **Property 5: PluginStore round-trip** — for any PluginRecord, save then load → equal
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 5: PluginStore round-trip`
    - **Validates: Requirements 4.1, 4.2**

  - [x]* 21.6 Write Property 6: Enable/Disable Toggles State Correctly
    - **Property 6: Enable/disable toggles state correctly** — disable→enable = enabled=True; enable→disable = enabled=False
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 6: Enable/disable toggles state correctly`
    - **Validates: Requirements 4.4, 4.5**

  - [x]* 21.7 Write Property 7: Search Results Are a Subset Matching the Query
    - **Property 7: Search results are a subset matching the query** — every result contains query; no matching entry is absent
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 7: Search results are a subset matching the query`
    - **Validates: Requirements 6.5**

  - [x]* 21.8 Write Property 8: Checksum Verification Correctness
    - **Property 8: Checksum verification correctness** — correct checksum passes; any other checksum fails
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 8: Checksum verification correctness`
    - **Validates: Requirements 6.6**

  - [x]* 21.9 Write Property 9: Installed Plugins API Round-Trip
    - **Property 9: Installed plugins API round-trip** — GET /plugins returns exactly the installed plugins
    - `@settings(max_examples=100)`
    - `# Feature: plugin-ecosystem, Property 9: Installed plugins API round-trip`
    - **Validates: Requirements 8.2**

- [x] 22. Final Checkpoint — all tests pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm all existing + new Phase 5 tests pass.
  - Verify `audiobuilder plugin list` runs without error.
  - Verify `GET /api/v1/plugins` returns 200.
  - Ask the user if questions arise.

- [x] 23. Update steering files
  - [x] 23.1 Update `plugin-development.md` — add manifest-based plugin section and lifecycle section
  - [x] 23.2 Update `project-overview.md` — add new env vars, file map entries, steering file index entry
  - [x] 23.3 Update `node-registry.md` — add note about `unregister()`
  - [x] 23.4 Update `api-endpoints.md` — add `/api/v1/plugins/` router section
  - [x] 23.5 Update `api-structure.md` — add `plugins_router` to Active Routers table
  - [x] 23.6 Update `sdk-cli.md` — add `Pipeline.install_plugin()` and `audiobuilder plugin` group

- [x] 24. Update project docs
  - [x] 24.1 Update `docs/PLUGIN_GUIDE.md` — add Phase 5 manifest section and CLI reference
  - [x] 24.2 Update `docs/USERGUIDE.md` — add Plugin Management section
  - [x] 24.3 Update `docs/API_REFERENCE.md` — add `/api/v1/plugins/` section
  - [x] 24.4 Update `docs/ARCHITECTURE.md` — add Phase 5 section
  - [x] 24.5 Update `docs/SDK_AND_CLI.md` — add `install_plugin()` and `plugin` CLI group

- [x] 25. Create `.kiro/steering/plugin-ecosystem.md` steering file
  - `fileMatchPattern: "app/core/plugins/**"`
  - Component overview, key invariants, error hierarchy, env vars, common patterns

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- All new files use `from __future__ import annotations` and Python 3.10+ type hints
- All workspace access uses `os.environ.get("GRAPHYN_PROJECT_DIR", "workspace")` — never hardcoded paths
- `PluginStore` and `PluginManager` are instantiated fresh per test using `tmp_path` + `monkeypatch`
- Network calls (`httpx.get`, `subprocess.run` for git) are always mocked in unit tests
- `PluginIndexClient._cache` must be reset to `None` in test teardown to prevent cross-test contamination
- `tomli` must be added to `requirements.txt` as a Python 3.10 backport for `tomllib`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2.1", "2.2"] },
    { "id": 1, "tasks": ["2.3", "3.1", "3.2"] },
    { "id": 2, "tasks": ["3.3", "4"] },
    { "id": 3, "tasks": ["5", "6.1", "6.2"] },
    { "id": 4, "tasks": ["6.3", "7.1", "7.2", "7.3"] },
    { "id": 5, "tasks": ["6.4", "7.4", "8"] },
    { "id": 6, "tasks": ["9.1", "9.2", "9.3", "10.1", "10.2"] },
    { "id": 7, "tasks": ["9.4", "10.3", "11.1"] },
    { "id": 8, "tasks": ["11.2", "11.3"] },
    { "id": 9, "tasks": ["11.4", "12"] },
    { "id": 10, "tasks": ["13", "14"] },
    { "id": 11, "tasks": ["15.1", "15.2", "15.3", "15.4", "16"] },
    { "id": 12, "tasks": ["17.1", "17.2", "18.1", "18.2", "19"] },
    { "id": 13, "tasks": ["17.3", "18.3", "19.1", "20"] },
    { "id": 14, "tasks": ["21.1", "21.2", "21.3", "21.4", "21.5", "21.6", "21.7", "21.8", "21.9"] },
    { "id": 15, "tasks": ["22"] },
    { "id": 16, "tasks": ["23.1", "23.2", "23.3", "23.4", "23.5", "23.6", "24.1", "24.2", "24.3", "24.4", "24.5", "25"] }
  ]
}
```
