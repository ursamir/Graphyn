# Functional Review — app/core/plugins/dependencies.py

**Group:** 4 — Plugin Ecosystem  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/plugins/dependencies.py
FUNCTION:    DependencyChecker._auto_install
CATEGORY:    Silent Failure Risk
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Attempt to install *unsatisfied* packages via pip. On success, log at INFO. On failure, raise `PluginDependencyError`.

WHAT IT ACTUALLY DOES:
After a successful `pip install`, the method returns without re-checking whether the packages are now actually importable. `pip install` can exit with code 0 even when the installation is incomplete or the package is installed into a different Python environment than the one running the platform (e.g. when `sys.executable` points to a venv but pip installs into the system Python, or when there are conflicting package versions that pip resolves by downgrading).

THE BUG / RISK:
`pip install` returns 0 (success), `_auto_install` returns without error, but the installed package is not importable in the current process. The plugin then fails at import time with an `ImportError` rather than a clear `PluginDependencyError`. The user sees a confusing traceback instead of "dependency not satisfied".

EVIDENCE:
```python
if result.returncode != 0:
    raise PluginDependencyError(...)
logger.info("Auto-installed plugin dependencies: %s", ...)
# No re-check of whether packages are now importable
```

REPRODUCTION SCENARIO:
Platform runs in a venv. `sys.executable` is `venv/bin/python`. `pip install scipy` succeeds (exit 0) but installs into a location not on `sys.path` (e.g. user site-packages that is excluded from the venv). The plugin entry point then fails with `ImportError: No module named 'scipy'`.

IMPACT:
Silent wrong result: `check()` returns without error, but the plugin will fail to import. The error surfaces later with a confusing traceback rather than a clear dependency error.

FIX DIRECTION:
After `pip install` succeeds, re-run `_find_unsatisfied(parsed)` and raise `PluginDependencyError` if any packages are still missing:
```python
still_missing = cls._find_unsatisfied(parsed_reqs)
if still_missing:
    raise PluginDependencyError(
        f"Auto-install reported success but packages are still not importable: "
        f"{', '.join(still_missing)}"
    )
```
(Requires passing `parsed` through to `_auto_install`, or re-parsing.)

--------------------------------------------------------------------
FILE:        app/core/plugins/dependencies.py
FUNCTION:    DependencyChecker._find_unsatisfied
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the subset of requirements not satisfied in the current environment.

WHAT IT ACTUALLY DOES:
Uses `importlib.metadata.version(req.name)` to check if a package is installed. `req.name` is the distribution name (e.g. `"Pillow"`), but `importlib.metadata` is case-sensitive on some platforms and the distribution name may differ from the import name (e.g. `"Pillow"` vs `"PIL"`, `"scikit-learn"` vs `"sklearn"`). If the distribution name in the requirement string does not exactly match the installed distribution name (case or hyphen/underscore normalization), `PackageNotFoundError` is raised and the package is incorrectly reported as unsatisfied.

THE BUG / RISK:
False positives: a package that is installed under a slightly different distribution name (e.g. `"Pillow"` vs `"pillow"`) is reported as unsatisfied, causing `PluginDependencyError` even though the package is available. This blocks plugin installation unnecessarily.

EVIDENCE:
```python
installed = pkg_version(req.name)   # case-sensitive on some platforms
```
`importlib.metadata` normalizes names per PEP 503 on Python 3.10+ but behavior varies.

REPRODUCTION SCENARIO:
Plugin declares `dependencies = ["Pillow>=9.0"]`. On a system where the distribution is registered as `"pillow"` (lowercase), `pkg_version("Pillow")` raises `PackageNotFoundError` on Python 3.9. The package is reported as unsatisfied even though `import PIL` works fine.

IMPACT:
False positive dependency errors block plugin installation. Low severity in practice on Python 3.10+ where normalization is consistent, but a real issue on 3.9.

FIX DIRECTION:
Use `importlib.metadata.packages_distributions()` or normalize the name per PEP 503 before lookup:
```python
from importlib.metadata import packages_distributions
normalized = req.name.lower().replace("-", "_").replace(".", "_")
```

--------------------------------------------------------------------
FILE:        app/core/plugins/dependencies.py
FUNCTION:    DependencyChecker.check
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Verify all dependencies; raise `PluginDependencyError` if unsatisfied and auto-install is disabled.

WHAT IT ACTUALLY DOES:
When `_auto_install_enabled()` returns `True`, calls `_auto_install(unsatisfied)` and returns immediately — without checking whether `_auto_install` succeeded. `_auto_install` raises `PluginDependencyError` on failure, which propagates correctly. However, `_auto_install` also has a `subprocess.TimeoutExpired` handler that raises `PluginDependencyError`. This is correct. The flow is:

```
check() → _auto_install() → raises PluginDependencyError on failure
                           → returns None on success (no re-check)
```

The only issue is the missing post-install verification (covered in finding #1 above). No additional finding here beyond what is already documented.

THE BUG / RISK:
`_auto_install_enabled()` calls `app.core.config.plugin_auto_install()` via a lazy import. If `app.core.config` raises an `ImportError` (e.g. missing dependency), `_auto_install_enabled()` propagates the `ImportError` rather than returning `False`. This would cause `check()` to raise `ImportError` instead of `PluginDependencyError`.

EVIDENCE:
```python
@staticmethod
def _auto_install_enabled() -> bool:
    from app.core.config import plugin_auto_install as _plugin_auto_install
    return _plugin_auto_install()   # ImportError propagates if config module fails
```

REPRODUCTION SCENARIO:
`app.core.config` has a missing dependency (e.g. `pydantic` not installed). `_auto_install_enabled()` raises `ImportError`. `check()` propagates `ImportError` instead of `PluginDependencyError`.

IMPACT:
Wrong exception type. Low probability since `app.core.config` is a core module.

FIX DIRECTION:
```python
try:
    from app.core.config import plugin_auto_install as _plugin_auto_install
    return _plugin_auto_install()
except Exception:
    return False
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
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `_auto_install` returns success without verifying packages are actually importable, allowing a plugin with unmet dependencies to proceed to the import stage |
