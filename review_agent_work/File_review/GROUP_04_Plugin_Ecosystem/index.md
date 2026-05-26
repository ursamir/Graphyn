# Functional Review — app/core/plugins/index.py

**Group:** 4 — Plugin Ecosystem  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/plugins/index.py
FUNCTION:    PluginIndexClient._fetch_remote
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Fetch the plugin index from a remote URL with a 10 MB size limit (G4-25 fix).

WHAT IT ACTUALLY DOES:
The class-level cache `_cache` is set inside the `_cache_lock` in `fetch()`. However, `_fetch_remote` is called while the lock is held. If `_fetch_remote` raises `PluginIndexError` (network error, non-2xx response, size exceeded), the exception propagates out of the `with _cache_lock` block. `_cache` remains `None`. The next call to `fetch()` will correctly retry the remote fetch. This is fine.

The real issue: `_cache` is a **class-level** attribute shared across all instances and all tests. There is no mechanism to reset it between test runs except manually setting `PluginIndexClient._cache = None`. If a test populates the cache with a mock index, subsequent tests (or production code in the same process) will use the stale cached data. The docstring acknowledges this: "Reset `_cache` to `None` in tests to prevent cross-test contamination." But this is a test-hostile design that is easy to forget.

THE BUG / RISK:
In production: if the index is fetched once with stale data (e.g. at startup before the index server is updated), all subsequent `lookup()` and `search()` calls in the same process will use the stale data for the lifetime of the process. There is no TTL, no cache invalidation, and no way to force a refresh without restarting the process.

EVIDENCE:
```python
_cache: list[PluginIndexEntry] | None = None   # class-level, no TTL
# ...
PluginIndexClient._cache = entries   # set once, never invalidated
```

REPRODUCTION SCENARIO:
Platform starts, fetches the index (100 plugins). An operator publishes a new plugin version. Any `lookup()` call in the same process will return the old version until the process is restarted.

IMPACT:
Stale plugin index: users cannot install newly published plugin versions without restarting the platform. Silent wrong result — `lookup()` returns an outdated entry without any indication that the cache is stale.

FIX DIRECTION:
Add a TTL to the cache (e.g. 5 minutes) using a timestamp:
```python
_cache: list[PluginIndexEntry] | None = None
_cache_time: float = 0.0
_CACHE_TTL: float = 300.0  # 5 minutes

# In fetch():
import time
if _cache is not None and (time.monotonic() - _cache_time) < _CACHE_TTL:
    return _cache
```

--------------------------------------------------------------------
FILE:        app/core/plugins/index.py
FUNCTION:    PluginIndexClient._fetch_remote
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Fetch the plugin index from a remote URL, raising `PluginIndexError` on failure.

WHAT IT ACTUALLY DOES:
```python
with httpx.stream("GET", url, timeout=10, follow_redirects=True) as response:
    if not response.is_success:
        raise PluginIndexError(...)
    for chunk in response.iter_bytes(chunk_size=65_536):
        ...
```

The `timeout=10` applies to the connection timeout but not to the read timeout for individual chunks. In `httpx`, a scalar timeout applies to all phases (connect, read, write, pool). However, if the server sends the response headers quickly (within 10 seconds) but then stalls between chunks, the 10-second timeout may not trigger because each individual chunk arrives within 10 seconds. A slow server could keep the connection open indefinitely by sending one byte every 9 seconds.

THE BUG / RISK:
A slow or malicious index server can keep the connection open indefinitely by trickling data, bypassing the 10-second timeout. The `_cache_lock` is held during the entire fetch, blocking all other threads that call `fetch()`.

EVIDENCE:
```python
with httpx.stream("GET", url, timeout=10, follow_redirects=True) as response:
    for chunk in response.iter_bytes(chunk_size=65_536):
        # each chunk arrives within 10s — timeout never triggers
```

REPRODUCTION SCENARIO:
A malicious index server sends 1 byte every 9 seconds. The 10-second timeout never fires. The `_cache_lock` is held for the duration, blocking all plugin operations.

IMPACT:
Denial of service: all plugin operations (install, search, lookup) are blocked while the lock is held.

FIX DIRECTION:
Use `httpx.Timeout` with a separate `read` timeout:
```python
timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
```

--------------------------------------------------------------------
FILE:        app/core/plugins/index.py
FUNCTION:    PluginIndexClient._fetch_remote
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Parse the fetched JSON and return a list of `PluginIndexEntry` objects.

WHAT IT ACTUALLY DOES:
```python
data = json.loads(b"".join(chunks))
plugins_raw = data.get("plugins", [])
return [PluginIndexEntry(**item) for item in plugins_raw]
```

If any single entry in `plugins_raw` fails `PluginIndexEntry` validation (e.g. a missing required field like `download_url`), the entire list comprehension raises `ValidationError` and `_fetch_remote` raises `PluginIndexError`. The entire index is discarded because of one malformed entry.

THE BUG / RISK:
One malformed entry in the remote index causes the entire index to be unavailable. All `lookup()` and `search()` calls fail with `PluginIndexError`. Users cannot install any plugin.

EVIDENCE:
```python
return [PluginIndexEntry(**item) for item in plugins_raw]   # one bad entry kills all
```

REPRODUCTION SCENARIO:
The index server publishes a new entry with a missing `download_url` field. `_fetch_remote` raises `PluginIndexError`. `_cache` is never set. All subsequent `fetch()` calls retry and fail. No plugins can be installed.

IMPACT:
Complete index unavailability due to one malformed entry. Silent from the user's perspective — they see "plugin not found" rather than "index has a malformed entry".

FIX DIRECTION:
Skip malformed entries with a warning:
```python
entries = []
for item in plugins_raw:
    try:
        entries.append(PluginIndexEntry(**item))
    except Exception as exc:
        logger.warning("Skipping malformed index entry %r: %s", item.get("name", "?"), exc)
return entries
```

--------------------------------------------------------------------
FILE:        app/core/plugins/index.py
FUNCTION:    PluginIndexClient.lookup
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Find a plugin by name, optionally filtered by a version constraint. When version parsing fails, falls back to exact string match.

WHAT IT ACTUALLY DOES:
```python
except Exception:
    # Fallback: exact string match if specifier parsing fails
    versioned = [e for e in matches if e.version == version_str]
```

The bare `except Exception` silently swallows the specifier parsing error and falls back to exact string matching. If the user passes a malformed version string (e.g. `"latest"` or `">="`), the fallback will find no matches (since no entry has `version == "latest"`), and `PluginNotFoundError` is raised with a message that says "no version satisfying 'latest'" — which is correct but doesn't explain that the version string was invalid.

THE BUG / RISK:
Silent swallowing of specifier parse errors. The user gets `PluginNotFoundError` instead of a clear "invalid version specifier" error.

EVIDENCE:
```python
except Exception:
    versioned = [e for e in matches if e.version == version_str]
```

REPRODUCTION SCENARIO:
`lookup("audio-classifier", version="latest")` → specifier parsing fails silently → exact match finds nothing → `PluginNotFoundError: Plugin 'audio-classifier' has no version satisfying 'latest'`.

IMPACT:
Confusing error message. No data corruption.

FIX DIRECTION:
Log the parse error before falling back:
```python
except Exception as exc:
    logger.debug("Version specifier '%s' is not valid PEP 440: %s — falling back to exact match", version_str, exc)
    versioned = [e for e in matches if e.version == version_str]
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | YES |
| Top Risk | Class-level cache with no TTL means stale index data is served for the entire process lifetime; one malformed index entry makes the entire index unavailable |
