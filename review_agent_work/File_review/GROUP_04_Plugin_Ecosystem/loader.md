# Functional Review — app/core/plugins/loader.py

**Group:** 4 — Plugin Ecosystem  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/plugins/loader.py
FUNCTION:    PluginLoader._import_entry_points
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Import each entry-point file and register its Node subclasses, returning the list of newly registered node_types.

WHAT IT ACTUALLY DOES:
Takes a snapshot of `self._registry._classes.keys()` before importing, then computes the set difference after all entry points are processed. However, it accesses `self._registry._classes` directly — a private dict — without holding any lock. If another thread is concurrently registering or unregistering node types (e.g. a parallel `install()` call), the `before` snapshot and the `after` snapshot can be inconsistent.

THE BUG / RISK:
Race condition: if a concurrent thread registers a node type between the `before` snapshot and the `after` snapshot, that type will appear in `new_types` even though this plugin did not register it. Conversely, if a type is unregistered between the two snapshots, it will be missing from `new_types`. The returned list is wrong, and the `PluginRecord` stored in the database will record incorrect node types.

EVIDENCE:
```python
before: set[str] = set(self._registry._classes.keys())   # line ~175
# ... entry point imports happen here (can be slow) ...
after: set[str] = set(self._registry._classes.keys())    # line ~192
new_types = sorted(after - before)
```

REPRODUCTION SCENARIO:
Two threads call `PluginManager.install()` simultaneously with different plugins. Both `_import_entry_points` calls snapshot `before` at nearly the same time, then both import their entry points. Each sees the other's types in `after - before`, so both records claim to own the other's node types.

IMPACT:
Silent wrong result: `PluginRecord.manifest` will list node types it does not own. On uninstall, `_unload_node_types` uses `inspect.getfile()` (not the stored list), so uninstall is unaffected — but any code that trusts the returned list from `install()` will have incorrect data.

FIX DIRECTION:
Acquire the registry's internal lock (if it has one) around the snapshot-import-snapshot sequence, or use a dedicated lock in `PluginLoader`. Alternatively, track which node types were registered by inspecting the source file path of each class rather than relying on set difference.

--------------------------------------------------------------------
FILE:        app/core/plugins/loader.py
FUNCTION:    PluginLoader._import_entry_points
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Individual entry-point failures are logged as WARNING and skipped; they do not abort loading of the remaining entry points."

WHAT IT ACTUALLY DOES:
Catches `DuplicateNodeTypeError` and bare `Exception` and continues. However, if an entry point raises a `SystemExit` or `KeyboardInterrupt` (both subclasses of `BaseException`, not `Exception`), the loop is aborted and the exception propagates up through `load()` without any cleanup or logging.

THE BUG / RISK:
A plugin entry point that calls `sys.exit()` or raises `KeyboardInterrupt` will abort the entire load sequence silently (from the plugin perspective). The `before` snapshot has been taken but `after` will never be computed, so `load()` raises instead of returning a partial list.

EVIDENCE:
```python
except Exception as exc:          # does not catch BaseException
    log.warning(...)
    continue
```

REPRODUCTION SCENARIO:
A malformed plugin entry point contains a top-level `sys.exit(1)` call. `_import_entry_points` propagates `SystemExit` up through `load()`, which propagates it through `PluginManager.install()`, which does clean up the install directory — but the error message is confusing.

IMPACT:
Crash / unexpected termination. Low probability but non-zero for malicious or buggy plugins.

FIX DIRECTION:
Catch `BaseException` (or at minimum `SystemExit`) in the inner loop and convert to a `PluginInstallError` or log + continue.

--------------------------------------------------------------------
FILE:        app/core/plugins/loader.py
FUNCTION:    PluginLoader._import_entry_points
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Returns the list of newly registered node_types.

WHAT IT ACTUALLY DOES:
If every entry point fails (all raise exceptions and are skipped), the function returns an empty list `[]` without raising any error. `load()` then logs "registered 0 node type(s)" and returns `[]`. The caller (`PluginManager.install()`) treats this as a successful install.

THE BUG / RISK:
A plugin that fails to register any node types is silently installed as a valid plugin with an empty node list. The user gets no error, and the plugin appears installed but is non-functional.

EVIDENCE:
```python
# All entry points skipped via continue → new_types = []
return new_types   # returns [] with no error
```
`load()` then logs success and returns `[]` to `install()`.

REPRODUCTION SCENARIO:
A plugin's `nodes.py` has a syntax error. `_import_file` raises `SyntaxError`, which is caught by `except Exception`, logged as WARNING, and skipped. `load()` returns `[]`. `install()` persists a `PluginRecord` with no node types.

IMPACT:
Silent wrong result: plugin is marked as installed and enabled but contributes nothing to the registry. User must inspect logs to discover the failure.

FIX DIRECTION:
After computing `new_types`, if it is empty and `manifest.entry_points` is non-empty, raise `PluginInstallError` (or at minimum log at ERROR level and return a failure indicator).

--------------------------------------------------------------------
FILE:        app/core/plugins/loader.py
FUNCTION:    PluginLoader._check_platform_compat
CATEGORY:    Silent Failure Risk
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Raise `PluginCompatibilityError` if the platform version does not satisfy the plugin's `platform_version` specifier; skip with WARNING if version is unknown.

WHAT IT ACTUALLY DOES:
When `_get_platform_version()` returns `None`, the check is silently skipped. This is documented as intentional (G4-06 fix). However, the WARNING message is only logged at WARNING level — it will be invisible in production environments configured with INFO-only logging unless the operator specifically watches for it.

THE BUG / RISK:
In a production deployment where `app.__version__` is not set (e.g. editable installs, CI), incompatible plugins will load without any compatibility enforcement. The WARNING is easy to miss.

EVIDENCE:
```python
if platform_ver is None:
    log.warning("PluginLoader: platform version unknown ...")
    return   # silently skips the check
```

REPRODUCTION SCENARIO:
Deploy the platform without setting `app.__version__`. Install a plugin that requires `platform_version = ">=99.0"`. The plugin loads without error.

IMPACT:
Incompatible plugin loaded silently; may crash at runtime when calling `process()`.

FIX DIRECTION:
This is a known trade-off (G4-06). Consider raising `PluginCompatibilityError` in strict mode (new env var `GRAPHYN_STRICT_COMPAT=1`) while keeping the skip behavior as default.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | `_import_entry_points` race condition between `before`/`after` snapshots produces incorrect node type lists under concurrent installs |
