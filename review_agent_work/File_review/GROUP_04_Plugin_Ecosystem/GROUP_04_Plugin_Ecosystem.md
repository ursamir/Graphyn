# Group Review Index — 4: Plugin Ecosystem

**Files reviewed:** 8  
**Total findings:** 22 (CRITICAL: 1 | HIGH: 8 | MEDIUM: 10 | LOW: 3)  
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| loader.md | HIGH | 2 | `_import_entry_points` race condition between `before`/`after` snapshots produces incorrect node type lists under concurrent installs |
| installer.md | HIGH | 1 | `_resolve_git` tmpdir cleanup fails when manifest is found at level 2 depth, leaking disk space on every such install |
| store.md | HIGH | 1 | A single corrupt `PluginRecord` in `registry.json` causes `list()` to raise, preventing all plugins from loading at startup |
| manager.md | CRITICAL | 1 | No concurrency guard on `install()` — concurrent installs of the same plugin name corrupt the install directory and registry state |
| dependencies.md | HIGH | 1 | `_auto_install` returns success without verifying packages are actually importable, allowing a plugin with unmet dependencies to proceed to the import stage |
| manifest.md | MEDIUM | 1 | Entry point path traversal (`..`) not blocked by validator — a malicious plugin can cause platform core files to be imported as entry points |
| errors.md | LOW | 0 | None — pure exception hierarchy, no logic to fail |
| index.md | HIGH | 1 | Class-level cache with no TTL means stale index data is served for the entire process lifetime; one malformed index entry makes the entire index unavailable |

---

## Priority Findings (CRITICAL and HIGH only)

**[CRITICAL] manager.md — PluginManager.install — No concurrency guard: concurrent installs of the same plugin name race on `shutil.rmtree` + `shutil.copytree`, corrupting the install directory and leaving the registry in an inconsistent state**

**[HIGH] manager.md — PluginManager.install — Upgrade via URL source unregisters the old plugin before the new plugin is fully installed; if `copytree` fails, the old plugin is permanently lost (data loss)**

**[HIGH] manager.md — PluginManager.enable — Dead `manifest` load + racy `before`/`after` set comparison for "already loaded" check; partially loaded state possible if load raises mid-way**

**[HIGH] loader.md — PluginLoader._import_entry_points — Race condition: `before`/`after` registry snapshots taken without a lock; concurrent installs produce incorrect node type lists in `PluginRecord`**

**[HIGH] loader.md — PluginLoader._import_entry_points — All entry points fail silently → `load()` returns `[]` and `install()` persists a non-functional plugin with no error raised**

**[HIGH] installer.md — PluginInstaller._resolve_git — Tmpdir cleanup fails when manifest is found at level 2 depth; `resolved_dir.parent` is not the `kiro_plugin_git_*` root, so the guard in `manager.py` skips cleanup → disk space leak**

**[HIGH] installer.md — PluginInstaller._resolve_git — No timeout on `subprocess.run` for git clone; a slow/unresponsive server blocks the worker thread indefinitely**

**[HIGH] store.md — PluginStore.get / list — `PluginRecord(**data[name])` raises raw `pydantic.ValidationError` on schema-mismatched records; callers catching `PluginNotFoundError` miss this exception**

**[HIGH] store.md — PluginStore.list — One corrupt record causes the entire `list()` to raise, making all plugins invisible and breaking `load_enabled_plugins()` at startup**

**[HIGH] dependencies.md — DependencyChecker._auto_install — Returns success without re-verifying packages are importable; plugin proceeds to import stage with unmet dependencies**

**[HIGH] index.md — PluginIndexClient._fetch_remote — Class-level cache has no TTL; stale index data served for entire process lifetime with no way to refresh without restart**

**[HIGH] index.md — PluginIndexClient._fetch_remote — One malformed `PluginIndexEntry` in the remote index causes the entire index to be discarded; all plugin installs fail**

---

## Most Dangerous File

**manager.md** — `PluginManager.install()` has no concurrency guard, making concurrent installs of the same plugin name a data-corruption race condition; additionally, the upgrade path can permanently destroy an existing plugin installation if the copy step fails after the old plugin has already been unregistered.
