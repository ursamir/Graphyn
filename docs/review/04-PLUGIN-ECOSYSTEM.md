# Plugin Ecosystem Review — `app/core/plugins/`

**Date:** 2026-05-18  
**Files:** `manager.py`, `loader.py`, `installer.py`, `manifest.py`, `store.py`, `errors.py`, `dependencies.py`, `index.py`

---

## `manager.py`

### PL-01 🔴 `install()` is not atomic — orphaned directory on failed load
The install sequence is:
1. Copy resolved dir to `{plugins_dir}/{manifest.name}/` ← disk write
2. Load the plugin (validate, register nodes) ← can fail here
3. Persist `PluginRecord` to store

If step 2 fails (e.g. `PluginCompatibilityError`, `PluginDependencyError`), the plugin directory exists on disk but no `PluginRecord` is in the store. A subsequent `install()` call skips the "already installed" check (nothing in the store) but finds the directory already exists and calls `shutil.rmtree` on it before copying again. This is the happy path. However, if the directory is partially written or corrupted, the cleanup may fail silently.

More critically: if step 2 fails after `shutil.copytree` but before `shutil.rmtree` in the upgrade path, the old plugin is gone and the new one is broken.

**Fix:** Wrap steps 4–8 in a try/except and clean up on failure:
```python
try:
    node_types = self._loader.load(install_path)
    record = PluginRecord(...)
    self._store.save(record)
except Exception:
    shutil.rmtree(install_path, ignore_errors=True)
    raise
```

---

### PL-02 🟠 `_unload_node_types` uses substring matching — false positives
```python
module_path_fragment = module_file.replace(".", os.sep)
if module_path_fragment in install_path_str or install_path_str in module_path_fragment:
    to_unregister.append(node_type)
```
A plugin installed at `/plugins/audio` would match a class from `/plugins/audio_denoiser` because `"audio"` is a substring of `"audio_denoiser"`. This would unregister node types from the wrong plugin.

**Fix:** Use exact path prefix matching with a separator boundary:
```python
source_file = inspect.getfile(cls)
resolved_source = Path(source_file).resolve()
if str(resolved_source).startswith(str(install_path) + os.sep):
    to_unregister.append(node_type)
```

---

### PL-03 🟠 `enable()` can trigger `DuplicateNodeTypeError` if nodes already loaded
```python
def enable(self, name: str) -> PluginRecord:
    record = self._store.get(name)
    if not record.enabled:
        self._loader.load(install_path)   # ← raises DuplicateNodeTypeError if already in registry
```
If the plugin's node types are already in the registry (e.g. loaded at startup), calling `enable()` will attempt to re-register them and raise `DuplicateNodeTypeError`.

**Fix:** Check the registry before loading:
```python
if not record.enabled:
    install_path = Path(record.install_path)
    # Only load if node types are not already registered
    manifest = load_manifest(install_path)
    # Check if any entry point's nodes are already registered
    already_loaded = any(
        nt in self._registry for nt in self._registry._classes
        # ... check against plugin's expected node types
    )
    if not already_loaded:
        self._loader.load(install_path)
```

---

### PL-04 🟡 `load_enabled_plugins()` called at `__init__.py` import time — test isolation problem
`PluginManager().load_enabled_plugins()` is called when `app.core.nodes` is first imported. Every test that imports from `app.core.nodes` triggers real plugin loading from disk. Tests must monkeypatch `PluginManager` or ensure the plugins directory is empty.

**Recommendation:** Add an environment variable `GRAPHYN_SKIP_PLUGIN_LOAD=1` that skips startup loading, for use in test environments.

---

## `loader.py`

### PL-05 🟠 `_get_platform_version()` returns `"0.0.0"` on failure — blocks all plugins
```python
except Exception:
    return "0.0.0"
```
If `app.__version__` is not set (common in development installs), all plugins with `platform_version = ">=1.0"` fail the compatibility check because `Version("0.0.0") not in SpecifierSet(">=1.0")`. This silently blocks all plugins from loading.

**Fix:** Return a permissive version on failure, or raise a clear error:
```python
except Exception:
    log.warning("Could not determine platform version — skipping platform compat check")
    return None  # and skip the check if None
```

---

### PL-06 🟡 Entry-point `DuplicateNodeTypeError` is caught as WARNING — ambiguous log message
When two entry points in the same plugin register the same node type, the second raises `DuplicateNodeTypeError` which is caught and logged as a WARNING. The warning message says "failed to load entry point" but doesn't identify the duplicate node type, making it hard to diagnose.

**Fix:** Catch `DuplicateNodeTypeError` separately and include the node type in the message:
```python
except DuplicateNodeTypeError as exc:
    log.warning(
        "PluginLoader: duplicate node type in entry point '%s' of plugin '%s': %s",
        entry_point, manifest.name, exc
    )
```

---

## `installer.py`

### PL-07 🔴 Temp directories from `_resolve_local_dir` are never deleted
```python
def _resolve_local_dir(self, path: Path) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="kiro_plugin_local_"))
    dest = tmpdir / path.name
    shutil.copytree(str(path), str(dest))
    return dest   # ← tmpdir is returned but never cleaned up
```
`PluginManager.install()` calls `shutil.copytree(str(resolved_dir), str(install_path))` to copy the temp dir to the final location, but never calls `shutil.rmtree(resolved_dir.parent)`. Every local-path install leaks a temp directory.

**Fix:** Use a context manager in `PluginManager.install()`:
```python
import contextlib, tempfile

with tempfile.TemporaryDirectory(prefix="kiro_plugin_") as tmpdir:
    resolved_dir = self._installer.resolve(source, tmpdir=Path(tmpdir))
    ...
```
Or clean up explicitly after the copy:
```python
resolved_dir = self._installer.resolve(source)
try:
    shutil.copytree(str(resolved_dir), str(install_path))
finally:
    shutil.rmtree(str(resolved_dir.parent), ignore_errors=True)
```

---

### PL-08 🟠 `_resolve_git` does not check if `git` is on PATH
```python
result = subprocess.run(
    ["git", "clone", "--depth", "1", clone_url, str(tmpdir)],
    capture_output=True, text=True,
)
```
If `git` is not installed, `subprocess.run` raises `FileNotFoundError` which is caught by the outer `except Exception` and re-raised as `PluginInstallError("Unexpected error cloning ...")`. The error message is confusing.

**Fix:**
```python
import shutil as _shutil
if _shutil.which("git") is None:
    raise PluginInstallError(
        "git is not installed or not on PATH. "
        "Install git to use git+URL plugin sources."
    )
```

---

### PL-09 🟠 No download size limit — DoS via large archive
```python
response = httpx.get(url, follow_redirects=True, timeout=30.0)
data = response.content   # ← loads entire response into memory
```
A malicious plugin index could return a multi-GB archive. The entire response is loaded into memory before extraction.

**Fix:** Stream the download with a size limit:
```python
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
chunks = []
total = 0
with httpx.stream("GET", url, follow_redirects=True, timeout=30.0) as r:
    r.raise_for_status()
    for chunk in r.iter_bytes(chunk_size=65536):
        total += len(chunk)
        if total > MAX_DOWNLOAD_BYTES:
            raise PluginInstallError(f"Download exceeds maximum size of {MAX_DOWNLOAD_BYTES} bytes")
        chunks.append(chunk)
data = b"".join(chunks)
```

---

### PL-10 🟡 Zip-slip guard uses `str.startswith` — vulnerable on case-insensitive filesystems
```python
if not str(member_path).startswith(str(dest_resolved)):
    raise PluginInstallError(...)
```
On macOS (case-insensitive HFS+) or Windows, `"/tmp/PLUGIN"` and `"/tmp/plugin"` are the same path but `startswith` would not catch the escape. 

**Fix:** Use `Path.is_relative_to()` (Python 3.9+):
```python
if not member_path.is_relative_to(dest_resolved):
    raise PluginInstallError(...)
```

---

## `manifest.py`

### PL-11 🟡 `PluginManifest.__init__` override is redundant
`PluginManifest.__init__` wraps `ValidationError` into `PluginManifestError`. However, `model_validate()` (used in `_parse_manifest_dict`) does NOT go through `__init__`. The `_rewrap_validation_error` call in `_parse_manifest_dict` handles this correctly. The `__init__` override is redundant and adds confusion about which code path is active.

**Fix:** Remove the `__init__` override and rely solely on `_rewrap_validation_error` in `_parse_manifest_dict`.

---

### PL-12 🔵 Slug validation error message is cryptic
```python
raise ValueError(f"'name' must match ^[a-z][a-z0-9_-]*$ (got {v!r})")
```
The raw regex is not user-friendly. 

**Fix:**
```python
raise ValueError(
    f"'name' must start with a lowercase letter and contain only "
    f"lowercase letters, digits, hyphens, or underscores (got {v!r})"
)
```

---

## `store.py`

### PL-13 🟠 Corrupt `registry.json` silently treated as empty — all plugins appear uninstalled
```python
except json.JSONDecodeError as exc:
    logger.warning("PluginStore: registry.json is corrupt ...")
    return {}
```
A corrupt registry (e.g. from a partial write) causes all installed plugins to appear uninstalled. The next `install()` call will re-install them, potentially overwriting working plugin directories.

**Fix:** Back up the corrupt file before treating it as empty:
```python
backup_path = self._registry_path.with_suffix(".json.corrupt")
shutil.copy2(self._registry_path, backup_path)
logger.warning("PluginStore: backed up corrupt registry to %s", backup_path)
return {}
```

---

### PL-14 🔵 `PluginRecord.manifest: dict` is untyped — no validation on load
When loading a `PluginRecord` from the registry file, the `manifest` field is a plain `dict` with no validation. A corrupt or manually edited registry entry could produce a `PluginRecord` with an invalid manifest dict that causes errors later when `manifest["entry_points"]` is accessed.

**Fix:** Validate the manifest dict against `PluginManifest` on load, or store only the fields needed at runtime (name, version, entry_points) rather than the full manifest.
