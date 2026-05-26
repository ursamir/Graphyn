# Functional Review — app/core/config.py

**Group:** 8 — Platform Infra  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/config.py
FUNCTION:    _env
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the value of env var `name`, stripped, or `default` if unset/empty.

WHAT IT ACTUALLY DOES:
Returns `default` when the env var is set to a non-empty string that is
entirely whitespace (e.g. `"   "`), because `.strip()` reduces it to `""`
which is falsy, triggering the `or default` branch.

THE BUG / RISK:
A user who sets `GRAPHYN_PROJECT_DIR="   "` (accidentally, e.g. via a shell
script with trailing spaces) silently gets the default `"workspace"` path
instead of an error. The same applies to `GRAPHYN_API_TOKEN` — a whitespace-
only token silently becomes no-auth mode, which is a security concern.

EVIDENCE:
```python
# Line ~50
return os.environ.get(name, "").strip() or default
```
`"   ".strip()` → `""` → falsy → returns `default` silently.

REPRODUCTION SCENARIO:
```python
os.environ["GRAPHYN_PROJECT_DIR"] = "   "
assert project_dir() == Path("workspace").resolve()  # silently uses default
```

IMPACT:
Silent wrong result. For `GRAPHYN_API_TOKEN`, a whitespace-only value silently
disables authentication. For path vars, the wrong directory is used without
any warning.

FIX DIRECTION:
Warn (or raise) when the raw value is non-empty but strips to empty:
```python
def _env(name: str, default: str = "") -> str:
    raw = os.environ.get(name, "")
    stripped = raw.strip()
    if raw and not stripped:
        import logging
        logging.getLogger(__name__).warning(
            "Env var %s is set to whitespace-only; using default %r", name, default
        )
    return stripped or default
```

--------------------------------------------------------------------
FILE:        app/core/config.py
FUNCTION:    project_dir
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the Graphyn project directory resolved to an absolute path.

WHAT IT ACTUALLY DOES:
Calls `Path(...).resolve()` which follows symlinks and resolves `..`. On
systems where the CWD does not exist (e.g. it was deleted after the process
started), `Path("workspace").resolve()` raises `FileNotFoundError` on some
Python versions / OS combinations.

THE BUG / RISK:
If the process CWD is deleted while the server is running, any call to
`project_dir()` (and all derived path functions) will raise unexpectedly
instead of returning a stable path.

EVIDENCE:
```python
# Line ~130
return Path(_env("GRAPHYN_PROJECT_DIR", default="workspace")).resolve()
```

REPRODUCTION SCENARIO:
Start server, delete CWD from another terminal, then trigger any API call
that calls `project_dir()`.

IMPACT:
Crash / unhandled exception in production. Low probability but non-zero.

FIX DIRECTION:
Use `Path(...).absolute()` instead of `.resolve()` for the default case, or
catch `OSError` and fall back to an absolute path constructed from the raw
string.

--------------------------------------------------------------------
FILE:        app/core/config.py
FUNCTION:    plugin_allowed_sources
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the list of allowed plugin source URL prefixes; empty list means all
sources allowed.

WHAT IT ACTUALLY DOES:
Splits on `","` and strips each element. If the env var is set to a single
comma `","`, the result is `[]` (empty list after filtering empty strings),
which means "all sources allowed" — the opposite of the user's intent to
restrict sources.

EVIDENCE:
```python
# Line ~115
return [prefix.strip() for prefix in raw.split(",") if prefix.strip()]
```
`","` → `["", ""]` → filtered to `[]` → all sources allowed.

REPRODUCTION SCENARIO:
`GRAPHYN_PLUGIN_ALLOWED_SOURCES=","` → `plugin_allowed_sources()` returns `[]`
→ installer allows all sources.

IMPACT:
Silent security bypass. Intended restriction is silently ignored.

FIX DIRECTION:
If `raw` is non-empty but the parsed list is empty, raise `ValueError`:
```python
if raw and not result:
    raise ValueError(
        f"GRAPHYN_PLUGIN_ALLOWED_SOURCES={raw!r} parsed to empty list; "
        "check for stray commas."
    )
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `_env()` silently treats whitespace-only `GRAPHYN_API_TOKEN` as no-auth, bypassing authentication. |
