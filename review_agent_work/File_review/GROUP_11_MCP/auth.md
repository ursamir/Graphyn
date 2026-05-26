# Functional Review — app/mcp/auth.py

**Group:** 11 — MCP
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/mcp/auth.py
FUNCTION:    check_auth
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate the auth token in tool arguments; return None if auth passes,
return a structured error dict if auth fails.

WHAT IT ACTUALLY DOES:
Compares `provided != token` using plain string equality. This is correct
for opaque bearer tokens. However, the comparison is NOT timing-safe —
it uses Python's built-in `!=` operator, which short-circuits on the first
differing byte. This makes the comparison vulnerable to timing side-channel
attacks where an attacker can measure response time differences to guess
the token one byte at a time.

THE BUG / RISK:
Timing oracle: an attacker who can send many MCP requests and measure
response latency can use a timing side-channel to recover the token
character by character. In a local stdio transport this is low risk, but
if the MCP server is ever exposed over a network transport (HTTP/SSE),
this becomes a real vulnerability.

EVIDENCE:
Line ~38:
```python
if provided != token:
```
Plain string inequality — not constant-time.

REPRODUCTION SCENARIO:
Attacker sends 10,000 requests with tokens of the form `"a..."`, `"b..."`,
`"c..."` etc., measuring response time. The correct first character takes
slightly longer to reject (more bytes compared before mismatch). Repeat
for each position.

IMPACT:
Token recovery via timing side-channel. Low risk on stdio transport;
HIGH risk if transport changes to HTTP.

FIX DIRECTION:
```python
import hmac
if not hmac.compare_digest(provided, token):
    return {"error": True, "error_type": "unauthorized", ...}
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/auth.py
FUNCTION:    check_auth
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return None if auth is not configured (GRAPHYN_API_TOKEN unset/empty).

WHAT IT ACTUALLY DOES:
Calls `_api_token()` which returns `""` when the env var is unset. The
check `if not token: return None` correctly allows all requests when no
token is configured. However, if `arguments` is `None` (not a dict), the
expression `(arguments or {}).get("_meta", {})` safely handles it. This
is correct.

THE BUG / RISK:
No bug — the `arguments or {}` guard handles None correctly. Low severity
note: the `provided` variable defaults to `""` when `_meta` is absent or
`auth_token` is absent. This means a caller that sends `_meta: {}` (no
`auth_token` key) gets the same error as one that sends a wrong token.
The error message correctly says "Provide the API token in _meta.auth_token"
so this is acceptable behavior.

EVIDENCE:
Line ~36: `provided = (arguments or {}).get("_meta", {}).get("auth_token", "")`

REPRODUCTION SCENARIO:
`check_auth(None)` → `provided = ""` → if token is set, returns unauthorized.
This is correct behavior.

IMPACT:
None — edge case is handled correctly.

FIX DIRECTION:
No fix needed.
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 0 |
| Error Handling | COMPLETE |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | Timing side-channel in token comparison — use `hmac.compare_digest` instead of `!=`. |
