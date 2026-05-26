# Functional Review — app/core/webhook.py

**Group:** 8 — Platform Infra  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/webhook.py
FUNCTION:    WebhookService._send
CATEGORY:    Async Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Perform the HTTP POST in a background thread. Logs warning on failure.
Never raises.

WHAT IT ACTUALLY DOES:
`_send()` is called in a `daemon=True` background thread. The `httpx.Client`
is used as a context manager (`with httpx.Client(...) as client`), which is
correct for synchronous use. However, `httpx` is imported lazily inside
`_send()` on every call. If `httpx` is not installed, the `ImportError` is
caught by the outer `except Exception` and logged as a warning — which is
acceptable. But the real issue is that `_send()` runs in a daemon thread:
if the main process exits while `_send()` is mid-request (e.g. during a
graceful shutdown), the daemon thread is killed without closing the HTTP
connection, potentially leaving the remote server with a half-received
request and no response.

THE BUG / RISK:
Daemon threads are killed immediately on process exit. An in-flight HTTP POST
may be truncated at the TCP level. The remote webhook endpoint receives a
partial body and may log an error or take a partial action. This is documented
as intentional ("fire-and-forget") but the docstring says "Never raises" and
"fire-and-forget" — the risk of partial delivery on shutdown is not documented
at the `notify()` call site.

EVIDENCE:
```python
# Lines ~130-138
        daemon=True,
    )
    thread.start()
```
No join, no shutdown hook, no way for callers to drain in-flight notifications.

REPRODUCTION SCENARIO:
Call `notify()` then immediately call `sys.exit()` or let the process exit
naturally. The daemon thread is killed mid-POST.

IMPACT:
Partial webhook delivery on process shutdown. Low probability in practice but
non-zero during graceful API server shutdown.

FIX DIRECTION:
This is a known trade-off of fire-and-forget. Document it explicitly in the
`notify()` docstring. For higher reliability, use `daemon=False` and provide
a `shutdown()` method that joins all pending threads with a timeout.

--------------------------------------------------------------------
FILE:        app/core/webhook.py
FUNCTION:    WebhookService._send / _is_private_host
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Re-validate the resolved IP at send time to prevent DNS rebinding attacks.

WHAT IT ACTUALLY DOES:
`_is_private_host()` calls `socket.gethostbyname()` which returns only the
first A record. A DNS rebinding attack works by having the DNS TTL expire
between the `save()`-time check and the `_send()`-time check, and returning
a private IP on the second resolution. The send-time check does call
`_is_private_host()` again, which is correct. However, `httpx` performs its
own DNS resolution independently of `socket.gethostbyname()`. The OS DNS
cache may return a different result to `httpx` than to `socket.gethostbyname()`
depending on timing and resolver implementation. The check and the actual
connection use different DNS resolution paths, so the rebinding window is
narrowed but not eliminated.

THE BUG / RISK:
An attacker with control of the DNS record can time the TTL expiry so that:
1. `_is_private_host()` in `_send()` resolves to a public IP (passes check).
2. `httpx` resolves to a private IP (actual connection goes to internal host).

EVIDENCE:
```python
# Lines ~155-168
            if _is_private_host(hostname):
                logger.warning(...)
                return
            ...
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=body)
```
Two separate DNS resolutions: `socket.gethostbyname()` then `httpx`'s own
resolver.

REPRODUCTION SCENARIO:
DNS rebinding: TTL=1s, first resolution → public IP (passes check), second
resolution (by httpx) → 192.168.1.1 (internal host).

IMPACT:
SSRF bypass. Internal services reachable via webhook POST. Security issue.

FIX DIRECTION:
Use `httpx`'s transport layer to intercept the resolved IP before the
connection is made (e.g. a custom `httpx.HTTPTransport` subclass that checks
the resolved address). Alternatively, resolve the IP once, verify it, then
connect directly to the IP with the `Host` header set manually — eliminating
the second DNS lookup.

--------------------------------------------------------------------
FILE:        app/core/webhook.py
FUNCTION:    WebhookService.notify
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Uses an in-memory cache populated on first call, invalidated by `save()`.

WHAT IT ACTUALLY DOES:
`_config_cache` is an instance variable. `WebhookService` is not a singleton
— if multiple instances are created (e.g. one per request in the API layer),
each instance has its own `_config_cache`. The cache is invalidated by
`save()` on the instance that called `save()`, but other instances retain
their stale cache indefinitely.

THE BUG / RISK:
If the API creates a new `WebhookService()` per request (common pattern),
calling `save()` on one instance does not invalidate the cache on other
instances. Subsequent `notify()` calls on other instances use the old URL
and event list.

EVIDENCE:
```python
# Line ~44
    def __init__(self) -> None:
        self._config_cache: dict | None = None
```
Instance-level cache, no class-level invalidation mechanism.

REPRODUCTION SCENARIO:
```python
svc1 = WebhookService()
svc1.notify("run.started", {})  # populates svc1._config_cache with old URL
svc2 = WebhookService()
svc2.save("https://new-endpoint.example.com", ["run.started"])
svc1.notify("run.started", {})  # still uses old URL from svc1._config_cache
```

IMPACT:
Webhook notifications sent to stale URL after reconfiguration. Silent wrong
behavior.

FIX DIRECTION:
Make `WebhookService` a singleton (module-level instance), or move the cache
to a class variable with a class-level `invalidate()` method, or remove the
cache entirely (disk read on every `notify()` is cheap for fire-and-forget).

--------------------------------------------------------------------
FILE:        app/core/webhook.py
FUNCTION:    WebhookService.save
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Persist webhook configuration to workspace/webhooks.json. Raises ValueError
for invalid URLs.

WHAT IT ACTUALLY DOES:
When `parsed.hostname` is `None` or empty (e.g. URL is `"http://"`), the
`if hostname:` guard skips the SSRF check entirely. A URL like `"http://"`
has `parsed.netloc == ""` which is caught by the earlier `if not parsed.netloc`
check — but `"http:///path"` has `parsed.netloc == ""` too and is caught.
However, `"http://[::1]/"` (IPv6 loopback) has `parsed.hostname == "::1"`,
which `socket.gethostbyname("::1")` may fail to resolve on some systems
(returns `gaierror`), causing `_is_private_host` to raise `ValueError`, which
is then re-raised — but the error message says "could not be resolved" rather
than "is a loopback address", which is misleading.

THE BUG / RISK:
IPv6 loopback addresses (`::1`, `::ffff:127.0.0.1`) may bypass the SSRF check
if `socket.gethostbyname()` fails to resolve them (it only handles IPv4 on
some platforms). `ipaddress.ip_address("::1").is_loopback` is `True`, but
`socket.gethostbyname("::1")` may raise `gaierror` on platforms where IPv6
is not configured, causing the check to raise `ValueError("could not be
resolved")` rather than `ValueError("resolves to loopback")`.

EVIDENCE:
```python
# Lines ~35-40
    try:
        addr_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(addr_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except socket.gaierror as exc:
        raise ValueError(f"Webhook URL hostname '{hostname}' could not be resolved: {exc}") from exc
```
`socket.gethostbyname("::1")` raises `gaierror` on IPv4-only systems.

REPRODUCTION SCENARIO:
`save("http://[::1]/hook", [])` on an IPv4-only system → raises
`ValueError("could not be resolved")` instead of blocking as loopback.
On a dual-stack system, `gethostbyname("::1")` may return `"::1"` which
`ipaddress.ip_address` handles correctly — but behavior is platform-dependent.

IMPACT:
Inconsistent SSRF protection across platforms. On some systems, IPv6 loopback
URLs are rejected with a misleading error; on others they may pass.

FIX DIRECTION:
Try to parse `hostname` as an IP address directly before calling
`gethostbyname`, to handle IPv6 literals without DNS resolution:
```python
try:
    ip = ipaddress.ip_address(hostname)
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
except ValueError:
    pass  # not a bare IP literal, proceed with DNS
```

--------------------------------------------------------------------
FILE:        app/core/webhook.py
FUNCTION:    WebhookService.load
CATEGORY:    Silent Failure
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Read webhook configuration. Returns {} if not configured.

WHAT IT ACTUALLY DOES:
Returns `{}` on any exception, including `json.JSONDecodeError` (corrupt file),
`PermissionError`, and `IsADirectoryError`. The warning log is the only
signal. Callers (specifically `notify()`) treat `{}` as "no webhook
configured" and silently skip all notifications.

THE BUG / RISK:
A corrupt `webhooks.json` silently disables all webhook notifications. The
operator has no way to know notifications are being dropped unless they
monitor logs.

EVIDENCE:
```python
# Lines ~100-105
        except Exception as exc:
            logger.warning("Failed to read webhooks.json: %s", exc)
            return {}
```

REPRODUCTION SCENARIO:
Write `webhooks.json` with truncated JSON (e.g. disk full during `save()`).
All subsequent `notify()` calls silently do nothing.

IMPACT:
Silent loss of webhook notifications. Operator unaware unless monitoring logs.

FIX DIRECTION:
This is acceptable for fire-and-forget, but the warning message should
include the file path and suggest remediation:
```python
logger.warning(
    "Failed to read webhooks config at %s: %s — webhook notifications disabled.",
    self.CONFIG_PATH, exc
)
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | DNS rebinding SSRF bypass: `_is_private_host()` and `httpx` use separate DNS resolution paths, leaving a race window where the check passes but the connection goes to an internal host. |
