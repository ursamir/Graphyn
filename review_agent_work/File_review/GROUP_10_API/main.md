# Functional Review — app/api/main.py

**Group:** 10 — API  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/api/main.py
FUNCTION:    _auth_dep
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Authenticate every request using a Bearer token when GRAPHYN_API_TOKEN is set.

WHAT IT ACTUALLY DOES:
When `credentials` is None (no Authorization header) AND a token is configured,
it raises 401 with `detail="Invalid or missing Bearer token"`. This is correct.
However, when `credentials.credentials` is an empty string `""` and the
configured token is also `""` (empty string), the condition `not token` short-
circuits and allows the request through — but an empty token is semantically
"auth not configured", which is the intended behaviour. The real risk is the
opposite: if `api_token()` returns a non-empty string but `credentials` is
`None`, the code correctly raises 401. No bug here on the happy path.

THE BUG / RISK:
`HTTPBearer(auto_error=False)` silently sets `credentials=None` for any
malformed Authorization header (e.g. `Authorization: Basic abc`, `Authorization:
Bearer`, `Authorization: notbearer`). The dependency then raises 401 with the
same message for all of these cases. This is acceptable behaviour, but the
`detail` string says "Invalid or missing" — callers cannot distinguish a missing
header from a malformed one. More importantly, `auto_error=False` means FastAPI
does NOT return 403 for scheme mismatches; it returns 401 via our code. This is
a minor contract mismatch (RFC 6750 says 401 for missing, 401 for invalid — so
the status codes are correct, but the scheme-mismatch case is silently folded
in).

EVIDENCE:
Line ~60: `_bearer = HTTPBearer(auto_error=False)`
Line ~64: `if credentials is None or credentials.credentials != token:`

REPRODUCTION SCENARIO:
`curl -H "Authorization: Basic dXNlcjpwYXNz" http://localhost:8001/api/v1/nodes`
→ Returns 401 "Invalid or missing Bearer token" (correct status, slightly
misleading message — not a security issue).

IMPACT:
No security impact. Minor UX issue: API clients cannot distinguish "no token
provided" from "wrong scheme used".

FIX DIRECTION:
Split the two cases in the error message:
```python
if credentials is None:
    raise HTTPException(status_code=401, detail="Missing Bearer token", ...)
if credentials.credentials != token:
    raise HTTPException(status_code=401, detail="Invalid Bearer token", ...)
```

--------------------------------------------------------------------
FILE:        app/api/main.py
FUNCTION:    module-level (static file mounts)
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Mount static file directories at startup, resolved from GRAPHYN_PROJECT_DIR.
Comment says "GRAPHYN_PROJECT_DIR MUST be set before importing this module".

WHAT IT ACTUALLY DOES:
`_OUTPUT_ROOT`, `_INPUT_ROOT`, and `_RUNS_ROOT` are computed at module import
time. `StaticFiles(directory=...)` is called at import time. If
`GRAPHYN_PROJECT_DIR` is not set, `datasets_output_dir()` / `datasets_input_dir()`
/ `runs_dir()` fall back to defaults under `"workspace"` (relative path). The
`mkdir(parents=True, exist_ok=True)` calls create those directories silently.

THE BUG / RISK:
In test environments or when the module is imported without setting
`GRAPHYN_PROJECT_DIR`, the static mounts silently bind to `workspace/datasets/output`,
`workspace/datasets/input`, and `workspace/runs` relative to the current working
directory at import time. If the CWD changes between import and request handling
(e.g. in a test runner), the static files will serve from the wrong directory.
There is no startup validation that the resolved paths are absolute or that they
point to the intended location. The comment warns about this but there is no
runtime assertion.

EVIDENCE:
Lines ~105–115: `_OUTPUT_ROOT = datasets_output_dir().resolve()` etc., then
`app.mount(...)` — all at module level.

REPRODUCTION SCENARIO:
```python
import os
os.chdir("/tmp")
import app.api.main  # mounts /tmp/workspace/... silently
```

IMPACT:
Silent wrong-directory serving. Files uploaded to the correct location are not
served; files from an unrelated directory may be served.

FIX DIRECTION:
Add an assertion or log a clear warning if the resolved paths are not under an
expected absolute root, or defer the mount to a FastAPI `startup` event handler
where the environment is guaranteed to be fully configured.

--------------------------------------------------------------------
FILE:        app/api/main.py
FUNCTION:    module-level (registry initialization)
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Explicitly populate the NodeRegistry singleton at startup via `_init_registry()`.

WHAT IT ACTUALLY DOES:
`_init_registry()` is called at module import time with no error handling. If
AutoDiscovery fails (e.g. a plugin module has a syntax error, a missing
dependency, or a circular import), the exception propagates and the entire
`app.api.main` module fails to import, crashing uvicorn startup with a
potentially cryptic traceback.

THE BUG / RISK:
A single broken plugin causes the entire API server to fail to start. There is
no try/except around `_init_registry()` to degrade gracefully (e.g. log the
error and continue with a partial registry).

EVIDENCE:
Lines ~50–54:
```python
from app.core.nodes import initialize_registry as _init_registry
_init_registry()
```

REPRODUCTION SCENARIO:
Install a plugin with a syntax error in its `nodes.py`. Start uvicorn. The
server fails to start entirely rather than starting with that plugin excluded.

IMPACT:
Full API server outage due to a single broken plugin. No graceful degradation.

FIX DIRECTION:
```python
try:
    _init_registry()
except Exception as exc:
    _logger.error("Registry initialization failed: %s", exc, exc_info=True)
    # Server starts with empty/partial registry; individual node lookups will 404
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | Registry init failure at import time crashes the entire API server with no graceful degradation. |
