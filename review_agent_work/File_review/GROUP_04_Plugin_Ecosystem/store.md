# Functional Review — app/core/plugins/store.py

**Group:** 4 — Plugin Ecosystem  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/plugins/store.py
FUNCTION:    PluginStore.get
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the `PluginRecord` for *name*, raising `PluginNotFoundError` when absent.

WHAT IT ACTUALLY DOES:
```python
def get(self, name: str) -> PluginRecord:
    with self._lock:
        data = self._load()
    if name not in data:
        raise PluginNotFoundError(name)
    return PluginRecord(**data[name])
```

The lock is released after `_load()` returns but before the `name not in data` check and `PluginRecord` construction. Another thread could call `delete(name)` between the lock release and the `PluginRecord(**data[name])` line. However, since `data` is a local dict (already loaded into memory), the delete in another thread only affects the file on disk — the local `data` dict is unaffected. So this specific race is benign for `get()`.

The real issue is in `list()`:
```python
def list(self) -> list[PluginRecord]:
    with self._lock:
        data = self._load()
    return [PluginRecord(**v) for v in data.values()]
```
The lock is released before iterating `data.values()`. Since `data` is a local copy, this is also safe. No actual bug here.

THE BUG / RISK:
However, `PluginRecord(**data[name])` can raise `ValidationError` if the stored dict has a corrupt or schema-mismatched entry (e.g. a field added in a newer version is missing in an old record). This `ValidationError` is not caught and propagates as an unhandled Pydantic error rather than a `PluginNotFoundError` or a dedicated `PluginManifestError`. Callers that catch only `PluginNotFoundError` will see an unexpected `ValidationError`.

EVIDENCE:
```python
return PluginRecord(**data[name])   # can raise pydantic.ValidationError
```
No try/except around this construction.

REPRODUCTION SCENARIO:
A `PluginRecord` was saved with an older schema that lacked the `manifest` field. After a platform upgrade that added `manifest` as required, `get()` raises `pydantic.ValidationError: manifest field required` instead of a `PluginError` subclass.

IMPACT:
Unhandled exception type leaks through the public API. API endpoints that call `manager.get()` will return a 500 instead of a meaningful error.

FIX DIRECTION:
```python
try:
    return PluginRecord(**data[name])
except Exception as exc:
    raise PluginManifestError(
        f"Corrupt record for plugin '{name}' in registry: {exc}"
    ) from exc
```

--------------------------------------------------------------------
FILE:        app/core/plugins/store.py
FUNCTION:    PluginStore._load
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Read `registry.json` and return its contents; back up corrupt files before returning empty dict.

WHAT IT ACTUALLY DOES:
Only catches `json.JSONDecodeError`. If the file exists but raises a different exception during `read_text()` (e.g. `PermissionError`, `OSError` due to a broken symlink, or `UnicodeDecodeError` for a non-UTF-8 file), the exception propagates uncaught through `_load()` and through every public method that calls it (`get`, `list`, `save`, `delete`, `update_enabled`).

THE BUG / RISK:
A `PermissionError` or `UnicodeDecodeError` on `registry.json` will crash any plugin operation with an unhandled OS-level exception rather than a `PluginError` subclass.

EVIDENCE:
```python
try:
    text = self._registry_path.read_text(encoding="utf-8")
    return json.loads(text)
except json.JSONDecodeError as exc:   # only catches JSON errors
    ...
```

REPRODUCTION SCENARIO:
`registry.json` is owned by root with mode 600. The platform runs as a non-root user. `_load()` raises `PermissionError` which propagates through `list_installed()` to the API, returning a 500.

IMPACT:
Crash / unhandled exception. All plugin operations fail with an OS error instead of a meaningful plugin error.

FIX DIRECTION:
Broaden the except clause:
```python
except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
    # back up and return {}
```

--------------------------------------------------------------------
FILE:        app/core/plugins/store.py
FUNCTION:    PluginStore._save
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Atomically write data to `registry.json` via a temp file + `os.replace()`.

WHAT IT ACTUALLY DOES:
Uses `tempfile.mkstemp()` which returns a raw file descriptor `fd`. The `fd` is passed to `os.fdopen()` inside a `with` block. If `os.fdopen(fd, ...)` itself raises (e.g. `OSError`), the raw `fd` is never closed. This is an edge case but represents a file descriptor leak.

THE BUG / RISK:
If `os.fdopen(fd, "w", encoding="utf-8")` raises, `fd` leaks. On Linux, each process has a limited number of file descriptors (default 1024). Repeated failures could exhaust the fd table.

EVIDENCE:
```python
fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:   # if this raises, fd leaks
        json.dump(data, fh, indent=2)
```

REPRODUCTION SCENARIO:
`os.fdopen` raises `OSError` (e.g. invalid fd on some platforms). The `fd` is never closed. Repeated calls exhaust the fd table.

IMPACT:
File descriptor leak. Low probability but non-zero.

FIX DIRECTION:
```python
fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
try:
    os.close(fd)  # close raw fd immediately
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp_path, self._registry_path)
except Exception:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise
```

--------------------------------------------------------------------
FILE:        app/core/plugins/store.py
FUNCTION:    PluginStore.list
CATEGORY:    Silent Failure Risk
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return all installed plugins as a list of `PluginRecord`.

WHAT IT ACTUALLY DOES:
```python
return [PluginRecord(**v) for v in data.values()]
```
If any single record in `registry.json` is corrupt (schema mismatch), the entire `list()` call raises `ValidationError` and returns nothing. There is no per-record error handling.

THE BUG / RISK:
One corrupt record in the registry causes `list()` to fail completely, making all installed plugins invisible. `load_enabled_plugins()` calls `list()` at startup — a single corrupt record prevents all plugins from loading.

EVIDENCE:
```python
return [PluginRecord(**v) for v in data.values()]   # no per-record try/except
```

REPRODUCTION SCENARIO:
Plugin `audio-classifier` has a corrupt record (missing `manifest` field). `list()` raises `ValidationError`. `load_enabled_plugins()` catches nothing (it calls `self._store.list()` without a try/except around the list call itself), so startup plugin loading fails entirely.

IMPACT:
All plugins fail to load at startup due to one corrupt record. Silent from the user's perspective — no plugins are available.

FIX DIRECTION:
```python
records = []
for name, v in data.items():
    try:
        records.append(PluginRecord(**v))
    except Exception as exc:
        logger.warning("Skipping corrupt plugin record '%s': %s", name, exc)
return records
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | A single corrupt `PluginRecord` in `registry.json` causes `list()` to raise, preventing all plugins from loading at startup |
