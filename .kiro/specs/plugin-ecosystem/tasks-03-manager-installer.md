# tasks-03 — PluginManager, PluginInstaller, and PluginIndexClient

## Overview

Implement `PluginManager` (lifecycle orchestration), `PluginInstaller` (source resolution), and `PluginIndexClient` (index fetch and search). These depend on tasks-01 and tasks-02.

## Tasks

- [x] 9. Implement `PluginInstaller` (`app/core/plugins/installer.py`)
  - [x] 9.1 Implement source string routing in `resolve(source, version_constraint=None) -> Path`
    - Route based on source string prefix/suffix:
      - `git+` prefix or `.git` suffix → `_resolve_git()`
      - `http://` or `https://` prefix + `.zip`/`.tar.gz` suffix → `_resolve_http_archive()`
      - `http://` or `https://` prefix (other) → `_resolve_git()` (treat as git URL)
      - Existing local directory → `_resolve_local_dir()`
      - Existing local `.zip`/`.tar.gz` file → `_resolve_local_archive()`
      - Plain name (optionally with `==version`) → `_resolve_index()`
    - _Requirements: req-04 §5.1–§5.5, §5.10_

  - [x] 9.2 Implement `_resolve_git()`, `_resolve_http_archive()`, `_resolve_local_dir()`, `_resolve_local_archive()`
    - `_resolve_git(url)`: `subprocess.run(["git", "clone", "--depth", "1", url, tmpdir])`; raise `PluginInstallError` on non-zero returncode with git stderr; call `_find_manifest_dir()`
    - `_resolve_http_archive(url, checksum=None)`: `httpx.get(url, timeout=30)`; raise `PluginInstallError` on HTTP error; optionally verify checksum; extract with `zipfile`/`tarfile`; call `_find_manifest_dir()`
    - `_resolve_local_dir(path)`: `shutil.copytree(path, tmpdir / path.name)`; return copy
    - `_resolve_local_archive(path)`: extract to tmpdir; call `_find_manifest_dir()`
    - All methods use `tempfile.TemporaryDirectory()` or `tempfile.mkdtemp()` for isolation
    - _Requirements: req-04 §5.1, §5.2, §5.4, §5.5, §5.6, §5.7, §5.9_

  - [x] 9.3 Implement `_find_manifest_dir()`, `_verify_checksum()`, `_parse_name_version()`
    - `_find_manifest_dir(root, source_label)`: search root and one level of subdirs for `plugin.toml` or `plugin.json`; raise `PluginInstallError` if not found within 2 levels
    - `_verify_checksum(data, checksum, url)`: parse `sha256:` prefix; compute `hashlib.sha256(data).hexdigest()`; raise `PluginInstallError` on mismatch
    - `_parse_name_version(s)`: split on `==`; return `(name, version_or_None)`
    - _Requirements: req-04 §5.8, req-05 §6.6_

  - [x]* 9.4 Write unit tests for `PluginInstaller`
    - Create `tests/test_plugin_installer.py`
    - Test `resolve("git+https://...")` calls `_resolve_git` (mock subprocess.run)
    - Test `resolve("https://.../plugin.zip")` calls `_resolve_http_archive` (mock httpx.get)
    - Test `resolve("/local/path")` with existing dir calls `_resolve_local_dir`
    - Test `resolve("plugin-name")` calls `_resolve_index` (mock PluginIndexClient)
    - Test `resolve("plugin-name==1.0.0")` passes version to index lookup
    - Test git clone failure → `PluginInstallError` with git stderr
    - Test HTTP 404 → `PluginInstallError` with status code
    - Test archive with no `plugin.toml` → `PluginInstallError`
    - Test checksum mismatch → `PluginInstallError`
    - Test checksum match → no error
    - Test temp files are cleaned up on failure (mock to raise, check tmpdir deleted)
    - Use `tmp_path` for local archive/dir tests
    - _Requirements: req-04 §5.1–§5.10_

- [x] 10. Implement `PluginIndexClient` (`app/core/plugins/index.py`)
  - [x] 10.1 Define `PluginIndexEntry` Pydantic model and implement `fetch()`, `search()`, `lookup()`
    - `PluginIndexEntry`: `name`, `version`, `description`, `author`, `tags`, `platform_version`, `download_url`, `homepage=None`, `checksum=None`
    - `fetch()`: check class-level `_cache`; if None, try remote URL (`GRAPHYN_PLUGIN_INDEX_URL`) then local file (`workspace/plugins/index.json`); cache result; return list
    - `search(query)`: call `fetch()`; filter by case-insensitive match in `name`, `description`, or `tags`
    - `lookup(name, version=None)`: filter by name; optionally filter by version specifier; return highest version; raise `PluginNotFoundError` if not found
    - _Requirements: req-05 §6.1–§6.9_

  - [x] 10.2 Implement remote and local fetch paths
    - Remote: `httpx.get(url, timeout=10)`; raise `PluginIndexError` on failure; parse JSON
    - Local: read `workspace/plugins/index.json`; raise `PluginIndexError` on parse failure; log WARNING if neither source available
    - _Requirements: req-05 §6.2, §6.3, §6.4, §6.7, §6.8_

  - [x]* 10.3 Write unit tests for `PluginIndexClient`
    - Create `tests/test_plugin_index.py`
    - Test `fetch()` with `GRAPHYN_PLUGIN_INDEX_URL` set → calls httpx.get (mock)
    - Test `fetch()` without URL → reads local `index.json`
    - Test `fetch()` with no URL and no local file → returns empty list, logs WARNING
    - Test `fetch()` caches result (second call does not re-fetch)
    - Test `search("denois")` returns entries matching name/description/tags
    - Test `search("DENOIS")` is case-insensitive
    - Test `search("xyz_not_found")` returns empty list
    - Test `lookup("audio-denoiser")` returns correct entry
    - Test `lookup("audio-denoiser", "1.2.0")` returns correct version
    - Test `lookup("nonexistent")` raises `PluginNotFoundError`
    - Test remote fetch failure → `PluginIndexError`
    - Reset `PluginIndexClient._cache = None` in test teardown
    - Use `tmp_path` and `monkeypatch` for env vars and local file
    - _Requirements: req-05 §6.1–§6.9_

- [x] 11. Implement `PluginManager` (`app/core/plugins/manager.py`)
  - [x] 11.1 Implement `install()` and `uninstall()`
    - `install(source, upgrade=False)`:
      1. `PluginInstaller().resolve(source)` → local plugin dir
      2. `load_manifest(plugin_dir)` → manifest
      3. Check if already installed; raise `PluginAlreadyInstalledError` if `upgrade=False`
      4. If upgrading: call `uninstall(manifest.name)` first
      5. `shutil.copytree(plugin_dir, plugins_dir / manifest.name)`
      6. `PluginLoader(registry).load(dest)` → node_types
      7. Create and save `PluginRecord` with `enabled=True`
      8. Return `PluginRecord`
    - `uninstall(name)`:
      1. `store.get(name)` → record (raises `PluginNotFoundError`)
      2. `_unload_node_types(record)` — unregister node types from registry
      3. `store.delete(name)`
      4. `shutil.rmtree(record.install_path)` if exists
    - _Requirements: req-03 §4.3, §4.6, §4.9_

  - [x] 11.2 Implement `enable()`, `disable()`, `list_installed()`, `get()`, `load_enabled_plugins()`
    - `enable(name)`: get record; if not enabled, call `PluginLoader.load()`; `store.update_enabled(name, True)`; return updated record
    - `disable(name)`: get record; if enabled, call `_unload_node_types()`; `store.update_enabled(name, False)`; return updated record
    - `list_installed()`: `store.list()`
    - `get(name)`: `store.get(name)` (raises `PluginNotFoundError`)
    - `load_enabled_plugins()`: iterate `store.list()`; for each `enabled=True` record, call `PluginLoader.load(Path(record.install_path))`; log WARNING on failure, continue
    - _Requirements: req-03 §4.4, §4.5, §4.8_

  - [x] 11.3 Implement `_unload_node_types(record)`
    - Parse `record.manifest["entry_points"]`
    - For each entry point, compute expected module name: `f"{Path(record.install_path).name}.{Path(ep).stem}"`
    - Find all node_types in registry where `cls.__module__ == module_name`
    - Call `registry.unregister(node_type)` for each
    - Log WARNING if any unregistered node types are referenced in loaded GraphIR (check is best-effort)
    - _Requirements: req-03 §4.4, §4.6, §4.7_

  - [x]* 11.4 Write unit tests for `PluginManager`
    - Create `tests/test_plugin_manager.py`
    - Test `install(local_dir)` → `PluginRecord` with `enabled=True`, node types registered
    - Test `install(local_dir)` twice without upgrade → `PluginAlreadyInstalledError`
    - Test `install(local_dir, upgrade=True)` → replaces existing installation
    - Test `uninstall(name)` → record removed, plugin dir deleted, node types unregistered
    - Test `uninstall("nonexistent")` → `PluginNotFoundError`
    - Test `disable(name)` → `enabled=False`, node types unregistered
    - Test `enable(name)` after disable → `enabled=True`, node types re-registered
    - Test `list_installed()` returns all records
    - Test `get(name)` returns correct record
    - Test `get("nonexistent")` → `PluginNotFoundError`
    - Test `load_enabled_plugins()` loads enabled plugins, skips disabled, logs WARNING on failure
    - Use `tmp_path` for workspace and plugins dir; create minimal plugin packages
    - _Requirements: req-03 §4.1–§4.10, req-08 §9.2–§9.8_

- [x] 12. Checkpoint — verify all existing tests still pass
  - Run `venv/bin/pytest tests/ -x --tb=short -q` and confirm zero regressions.
  - Ask the user if questions arise.
