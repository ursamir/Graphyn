# Functional Review — app/api/routers/plugins.py

**Group:** 10 — API  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/api/routers/plugins.py
FUNCTION:    install_plugin (remote path via BackgroundTasks)
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
For remote sources, install runs in the background via `background_tasks.add_task()`.
Returns `{"status": "installing", "name": "<name>"}` immediately. The docstring
says "Poll GET /plugins/{name} for the final result."

WHAT IT ACTUALLY DOES:
`background_tasks.add_task(_bg_install)` schedules `_bg_install` to run after
the response is sent. Inside `_bg_install`, ALL exceptions are caught and
logged — including `PluginAlreadyInstalledError`, `PluginCompatibilityError`,
etc. The caller receives `{"status": "installing"}` and has no way to know
if the install succeeded or failed other than polling `GET /plugins/{name}`.

THE BUG / RISK:
If the background install fails (e.g. network error, checksum mismatch,
incompatible plugin), the failure is only logged — it is never written to any
persistent store that `GET /plugins/{name}` can surface. `GET /plugins/{name}`
will return 404 (plugin not found) after a failed install, which is
indistinguishable from "install still in progress". The caller cannot
distinguish "install failed" from "install still running".

EVIDENCE:
`plugins.py` lines ~148–160:
```python
def _bg_install() -> None:
    try:
        mgr = PluginManager()
        mgr.install(source, upgrade=upgrade, expected_sha256=expected_sha256)
        log.info("Background install of '%s' completed.", parsed_name)
    except Exception as exc:
        log.error("Background install of '%s' failed: %s", parsed_name, exc, exc_info=True)
```
Failure is only logged. No status written to a store.

REPRODUCTION SCENARIO:
1. POST /plugins/install with a remote URL that returns a 404.
2. Response: `{"status": "installing", "name": "myplugin"}`.
3. Poll GET /plugins/myplugin → 404 forever.
4. Caller cannot tell if install is still running or has failed.

IMPACT:
Silent failure for remote installs. Callers have no reliable way to detect
install failures. The "poll for result" pattern is broken because there is no
failure state to poll.

FIX DIRECTION:
Write a failure status to a persistent store (e.g. a `PluginStore` entry with
`status="failed"` and `error=str(exc)`) so that `GET /plugins/{name}` can
return the failure reason. Alternatively, use a job-tracking endpoint.

--------------------------------------------------------------------
FILE:        app/api/routers/plugins.py
FUNCTION:    install_plugin (remote path)
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Remote installs run in the background via `BackgroundTasks`. The module also
defines a `_install_executor = ThreadPoolExecutor(max_workers=4)` but it is
never used in the current code.

WHAT IT ACTUALLY DOES:
`_install_executor` is defined at module level but never referenced in any
function. It is dead code. However, it creates 4 worker threads at module
import time (or on first use, depending on Python version) that are never
used and never shut down.

EVIDENCE:
`plugins.py` line ~42: `_install_executor = ThreadPoolExecutor(max_workers=4)`
No reference to `_install_executor` anywhere else in the file.

REPRODUCTION SCENARIO:
Import `app.api.routers.plugins`. `_install_executor` is created with 4 idle
threads that are never used and never shut down cleanly.

IMPACT:
4 idle threads leaked per process. Minor resource waste. The executor is never
shut down, so on process exit Python may log a `ResourceWarning`.

FIX DIRECTION:
Remove `_install_executor` entirely since `BackgroundTasks` is used instead.

--------------------------------------------------------------------
FILE:        app/api/routers/plugins.py
FUNCTION:    install_plugin (synchronous path)
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
For local sources, install runs synchronously and returns the installed plugin
record. Known plugin exceptions are mapped to HTTP status codes.

WHAT IT ACTUALLY DOES:
The `except` clause catches exactly the 6 known plugin exception types. Any
OTHER exception from `manager.install()` (e.g. `OSError` for disk full,
`PermissionError` for filesystem permissions, `RuntimeError` from pip) is
not caught and propagates as an unhandled 500 with a raw Python traceback.

EVIDENCE:
`plugins.py` lines ~168–178:
```python
try:
    record = manager.install(source, upgrade=upgrade, expected_sha256=expected_sha256)
except (
    PluginNotFoundError, PluginAlreadyInstalledError, PluginCompatibilityError,
    PluginDependencyError, PluginInstallError, PluginIndexError,
) as exc:
    raise _plugin_http_error(exc) from exc
```
No catch-all for unexpected exceptions.

REPRODUCTION SCENARIO:
`manager.install()` raises `OSError: [Errno 28] No space left on device`.
Client receives 500 with raw Python traceback.

IMPACT:
Raw traceback exposed to API clients for unexpected install errors. Potential
information disclosure.

FIX DIRECTION:
Add a catch-all:
```python
except Exception as exc:
    raise HTTPException(status_code=500, detail={"error": "UnexpectedError", "detail": str(exc)}) from exc
```

--------------------------------------------------------------------
FILE:        app/api/routers/plugins.py
FUNCTION:    _parse_name_from_source
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Best-effort extraction of a plugin name from an arbitrary source string.

WHAT IT ACTUALLY DOES:
Instantiates `PluginInstaller()` just to call `_parse_name_version(source)`.
`PluginInstaller()` is a class that may have side effects in its constructor
(e.g. reading config, initializing state). This is called on every remote
install request just to extract a name string.

THE BUG / RISK:
If `PluginInstaller.__init__()` raises (e.g. config not available, filesystem
error), `_parse_name_from_source()` raises before the background task is even
scheduled. The caller gets a 500 instead of the expected `{"status": "installing"}`.
The docstring says "best-effort" but the implementation can fail hard.

EVIDENCE:
`plugins.py` lines ~57–59:
```python
installer = PluginInstaller()
name, _ = installer._parse_name_version(source)
```

REPRODUCTION SCENARIO:
`PluginInstaller.__init__()` raises `FileNotFoundError` (plugins dir missing).
`POST /plugins/install` with a remote URL → 500 instead of `{"status": "installing"}`.

IMPACT:
Remote install requests fail with 500 if PluginInstaller constructor raises.
The name extraction is best-effort but the constructor failure is not.

FIX DIRECTION:
Wrap in try/except and fall back to a simple string extraction:
```python
try:
    installer = PluginInstaller()
    name, _ = installer._parse_name_version(source)
except Exception:
    name = source.rsplit("/", 1)[-1].split("?")[0].rstrip(".git")
```

--------------------------------------------------------------------
FILE:        app/api/routers/plugins.py
FUNCTION:    enable_plugin
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Enable the plugin named *name* and reload its node types.

WHAT IT ACTUALLY DOES:
Catches `PluginNotFoundError`, `PluginCompatibilityError`, and
`PluginDependencyError`. Does NOT catch `PluginInstallError` or
`PluginIndexError`. If enabling a plugin triggers a dependency install that
fails with `PluginInstallError`, the exception propagates as an unhandled 500.

EVIDENCE:
`plugins.py` lines ~196–202:
```python
try:
    record = manager.enable(name)
except PluginNotFoundError as exc:
    raise _plugin_http_error(exc) from exc
except (PluginCompatibilityError, PluginDependencyError) as exc:
    raise _plugin_http_error(exc) from exc
```
`PluginInstallError` not caught.

REPRODUCTION SCENARIO:
Enabling a plugin triggers auto-install of a missing dependency. The install
fails with `PluginInstallError`. Client receives 500 instead of 502.

IMPACT:
Wrong HTTP status code (500 instead of 502) for install failures during enable.

FIX DIRECTION:
Add `PluginInstallError` to the caught exceptions:
```python
except (PluginCompatibilityError, PluginDependencyError, PluginInstallError) as exc:
    raise _plugin_http_error(exc) from exc
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
| Test Hostile | PARTIAL |
| Top Risk | Remote plugin install failures are silently swallowed — callers receive "installing" status and have no way to detect or retrieve the failure reason. |
