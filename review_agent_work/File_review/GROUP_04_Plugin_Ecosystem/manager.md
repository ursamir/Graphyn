# Functional Review — app/core/plugins/manager.py

**Group:** 4 — Plugin Ecosystem  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/plugins/manager.py
FUNCTION:    PluginManager.install
CATEGORY:    State Bug
SEVERITY:    CRITICAL
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Install a plugin atomically: resolve → manifest → copy → load → persist. If load or persist fails, remove the install directory so the next call starts clean.

WHAT IT ACTUALLY DOES:
There is no concurrency guard on `install()`. Two concurrent calls with the same plugin name (or two plugins that happen to have the same `manifest.name`) will both pass the pre-flight duplicate check (Step 2), both resolve their sources, both copy to `install_path`, and both attempt to load and persist. The second `shutil.copytree` will fail because `install_path.exists()` is True and `shutil.rmtree(install_path)` was called — but between the `rmtree` and the second `copytree`, the first thread may have already written its copy. The result is a race between two `shutil.rmtree` + `shutil.copytree` sequences on the same directory.

THE BUG / RISK:
Race condition on concurrent installs of the same plugin name:
1. Thread A and Thread B both pass the duplicate check.
2. Thread A calls `shutil.rmtree(install_path)` then `shutil.copytree(...)`.
3. Thread B calls `shutil.rmtree(install_path)` (deletes Thread A's copy) then `shutil.copytree(...)`.
4. Thread A's `_loader.load(install_path)` now operates on Thread B's files (or a partially deleted directory).
5. Both threads call `self._store.save(record)` — the last writer wins, but the registry may have node types from both plugins registered.

EVIDENCE:
```python
# No lock anywhere in install()
if install_path.exists():
    shutil.rmtree(install_path, ignore_errors=True)   # race window
plugins_dir.mkdir(parents=True, exist_ok=True)
shutil.copytree(str(resolved_dir), str(install_path))  # race window
```

REPRODUCTION SCENARIO:
Two API requests call `POST /plugins/install` with the same source simultaneously. Both pass the duplicate check, both delete and re-copy the install directory, both load and persist — resulting in a corrupt or inconsistent plugin state.

IMPACT:
Data corruption: the registry may contain node types from a partially-loaded plugin, or the `PluginRecord` may not match the actual files on disk. Subsequent `uninstall()` or `enable()` calls may fail or operate on wrong data.

FIX DIRECTION:
Add a per-plugin-name lock (or a global install lock) around the entire install sequence:
```python
with self._install_lock:
    # Steps 2–8
```
Use a `threading.Lock` or a dict of per-name locks.

--------------------------------------------------------------------
FILE:        app/core/plugins/manager.py
FUNCTION:    PluginManager.install
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Step 3: "If upgrade and already installed, call uninstall first."

WHAT IT ACTUALLY DOES:
The pre-flight uninstall uses `_pre_name` (parsed from the source string before resolving). For URL sources (git+, http://), `_pre_name` is the raw URL string (e.g. `"git+https://github.com/org/plugin.git"`). `self._store.get("git+https://...")` will raise `PluginNotFoundError`, so `existing` is `None`, and the pre-flight uninstall is skipped. The authoritative check at Step 5 uses `manifest.name` and correctly handles this case. However, between Step 3 (pre-flight uninstall with wrong name) and Step 5 (authoritative check), the `resolved_dir` has already been fetched (Step 4). If the authoritative check finds an existing plugin and calls `self.uninstall(manifest.name)`, this uninstall happens *after* the source has been resolved — meaning the old plugin's node types are unregistered while the new plugin's files are being copied. If the copy fails, the old plugin is gone from the registry but its files may still be on disk, leaving the system in an inconsistent state.

THE BUG / RISK:
During upgrade via URL source: old plugin is unregistered (Step 5 authoritative uninstall) before the new plugin is fully installed. If `shutil.copytree` or `_loader.load` fails, the old plugin is gone from the registry but its directory may still exist on disk. The `PluginRecord` is also deleted. The plugin is effectively lost.

EVIDENCE:
```python
# Step 5 — authoritative uninstall during upgrade
if auth_existing is not None and upgrade:
    self.uninstall(manifest.name)   # deletes record + unregisters nodes
# Step 6 — copy (can fail)
shutil.copytree(str(resolved_dir), str(install_path))  # if this fails...
# ...old plugin is gone, new plugin not installed
```

REPRODUCTION SCENARIO:
`manager.install("git+https://github.com/org/plugin.git", upgrade=True)` where the plugin is already installed. The git clone succeeds, the authoritative uninstall runs, then `shutil.copytree` fails (disk full). The old plugin is unregistered and its record deleted; the new plugin is not installed.

IMPACT:
Data loss: the plugin is permanently removed from the registry with no way to recover without manual intervention.

FIX DIRECTION:
Implement a proper upgrade sequence: copy new files to a staging directory first, then atomically swap (rename) the old directory to a backup, copy new files to the final location, and only then unregister old node types and register new ones. Roll back to the backup if any step fails.

--------------------------------------------------------------------
FILE:        app/core/plugins/manager.py
FUNCTION:    PluginManager.enable
CATEGORY:    Contract Mismatch
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Enable the plugin named *name* and reload its node types if not already loaded."

WHAT IT ACTUALLY DOES:
```python
record = self._store.get(name)
if not record.enabled:
    install_path = Path(record.install_path)
    try:
        from app.core.plugins.manifest import load_manifest
        manifest = load_manifest(install_path)   # loaded but never used
        before = set(self._registry._classes.keys())
        self._loader.load(install_path)
        after = set(self._registry._classes.keys())
        if after == before:
            log.debug("... skipped reload.")
    except Exception as exc:
        log.warning("Failed to reload plugin '%s' during enable: %s", name, exc)
        raise
updated = self._store.update_enabled(name, enabled=True)
```

The `manifest` variable is loaded but never used — it is dead code. More critically: if `self._loader.load(install_path)` raises, the exception is re-raised *before* `self._store.update_enabled(name, enabled=True)` is called. This means the plugin's `enabled` flag in the store remains `False` even though the caller receives an exception. This is correct behavior — but the docstring says "reload its node types if not already loaded", implying the method should be idempotent. If `load()` partially registers some node types before raising, those types are now in the registry but the store still says `enabled=False`. The state is inconsistent.

THE BUG / RISK:
Partial load during `enable()`: if `_loader.load()` registers some node types then raises (e.g. second entry point fails), those types are in the registry but the store says `enabled=False`. A subsequent `enable()` call will try to load again, potentially registering duplicates (though `DuplicateNodeTypeError` is caught and logged).

EVIDENCE:
```python
self._loader.load(install_path)   # may partially register nodes then raise
# ...
raise   # re-raised before update_enabled is called
# store still has enabled=False, but some nodes may be in registry
```

REPRODUCTION SCENARIO:
Plugin has two entry points. First loads successfully (registers 3 node types). Second has a syntax error (raises `SyntaxError`, caught by `_import_entry_points` as WARNING). `load()` returns `[]` (zero new types from this call, since the 3 types were already registered from a previous partial load). Actually — wait: if this is the first `enable()` call, `load()` returns the 3 types from the first entry point. But if the second entry point raises something that escapes `_import_entry_points`... Actually `_import_entry_points` catches all `Exception`. So `load()` itself won't raise from entry point failures. The raise path in `enable()` is triggered by `load_manifest()` or `DependencyChecker` failures. In that case, no nodes are registered, and the state is consistent. The dead `manifest` variable is the main issue here.

THE BUG / RISK (revised):
The `manifest = load_manifest(install_path)` call is dead code — the result is never used. This is a contract mismatch (the code implies it was going to use the manifest for something, e.g. checking which node types are already registered, but that logic was never completed). The actual node-type-already-loaded check uses `before == after` comparison, which has the same race condition as identified in `loader.py`.

EVIDENCE:
```python
manifest = load_manifest(install_path)   # result never used — dead code
before = set(self._registry._classes.keys())
self._loader.load(install_path)
after = set(self._registry._classes.keys())
if after == before:
    log.debug("... skipped reload.")
```

REPRODUCTION SCENARIO:
Any call to `enable()` on a disabled plugin. The manifest is loaded and discarded. The "already loaded" check is based on set comparison, not on the manifest's declared node types.

IMPACT:
Dead code creates maintenance confusion. The `before == after` check is also racy (same issue as `loader.py` finding #1).

FIX DIRECTION:
Remove the dead `manifest` load, or use it to check which node types the plugin declares and compare against the registry directly.

--------------------------------------------------------------------
FILE:        app/core/plugins/manager.py
FUNCTION:    PluginManager._unload_node_types
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Unload all node types contributed by *record* from the registry using `inspect.getfile()` to match source files.

WHAT IT ACTUALLY DOES:
Calls `self._registry.unregister(node_type)` for each matched type. If `unregister()` raises (e.g. the type was already unregistered by a concurrent call), the exception propagates out of `_unload_node_types`, which propagates out of `uninstall()` or `disable()`. The `PluginRecord` has already been deleted from the store (Step 3 of `uninstall()`) before `_unload_node_types` is called — wait, actually looking at the code:

```python
# Step 2 — unload node types from registry
self._unload_node_types(record)

# Step 3 — delete record from store
self._store.delete(name)
```

`_unload_node_types` is called *before* `_store.delete`. If `_unload_node_types` raises, `_store.delete` is never called, leaving the record in the store but the node types potentially partially unregistered.

THE BUG / RISK:
If `self._registry.unregister(node_type)` raises for one node type (e.g. concurrent unregister), the loop aborts. Some node types are unregistered, some are not. The `PluginRecord` remains in the store (since `_store.delete` was not reached). The plugin appears installed but has partial node type coverage.

EVIDENCE:
```python
for node_type in to_unregister:
    self._registry.unregister(node_type)   # can raise; no try/except
```

REPRODUCTION SCENARIO:
Concurrent `uninstall()` calls for the same plugin. First call unregisters node type `audio.classifier`. Second call also tries to unregister `audio.classifier` — `unregister()` raises `KeyError` or similar. Second call's `_unload_node_types` aborts mid-loop. `_store.delete` is never called. Plugin record remains in store.

IMPACT:
Inconsistent state: plugin record exists in store but node types are partially unregistered.

FIX DIRECTION:
Wrap each `unregister()` call in a try/except, or ensure `unregister()` is idempotent (no-op if not registered).

--------------------------------------------------------------------
FILE:        app/core/plugins/manager.py
FUNCTION:    PluginManager.load_enabled_plugins
CATEGORY:    Silent Failure Risk
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load all enabled plugins at startup; failures are logged at WARNING and do not abort startup.

WHAT IT ACTUALLY DOES:
Calls `self._store.list()` without a try/except. If `_store.list()` raises (e.g. `PermissionError` on `registry.json`, or a corrupt record causing `ValidationError` — see `store.py` finding), the entire `load_enabled_plugins()` call raises, and no plugins are loaded at startup. The docstring says "Failures are logged at WARNING level and do not abort startup" — but this only applies to per-plugin `_loader.load()` failures, not to the `_store.list()` call itself.

THE BUG / RISK:
A single corrupt `registry.json` or permission error causes `load_enabled_plugins()` to raise, preventing all plugins from loading at startup. The docstring's guarantee ("do not abort startup") is violated.

EVIDENCE:
```python
records = self._store.list()   # no try/except — can raise
for record in records:
    ...
```

REPRODUCTION SCENARIO:
`registry.json` has a corrupt record (missing required field). `_store.list()` raises `ValidationError`. `load_enabled_plugins()` propagates the exception. Platform startup fails to load any plugins.

IMPACT:
All plugins unavailable at startup due to one corrupt record.

FIX DIRECTION:
```python
try:
    records = self._store.list()
except Exception as exc:
    log.warning("Startup: failed to read plugin registry: %s", exc, exc_info=True)
    return
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | CRITICAL |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | No concurrency guard on `install()` — concurrent installs of the same plugin name corrupt the install directory and registry state |
