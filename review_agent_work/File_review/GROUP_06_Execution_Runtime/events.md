# Functional Review — app/core/events.py

**Group:** 6 — Execution Runtime  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/events.py
FUNCTION:    FileWatcherSource.watch
CATEGORY:    Async Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Watch a directory for new or modified files; yield event payloads indefinitely
until cancelled.

WHAT IT ACTUALLY DOES:
In the `watchfiles` path, the `async for changes in watchfiles.awatch(...)` loop
runs inside a `try/except ImportError` block. If `watchfiles` is installed but
raises a non-`ImportError` exception (e.g., `PermissionError` on the watched
directory, `OSError` if the directory is deleted, or `RuntimeError` from the
Rust backend), the exception propagates out of `watch()` uncaught. The caller
(`_handle_source` in orchestrator.py) does not catch exceptions from
`source.watch()` — it only iterates `async for payload in source.watch()`.
An uncaught exception from `watch()` will propagate to `asyncio.gather` as a
task exception, which is caught by `return_exceptions=True` and silently
discarded.

THE BUG / RISK:
A `watchfiles` backend error (directory deleted, permission denied, Rust thread
crash) causes the `FileWatcherSource` to silently stop yielding events. The
pipeline continues running but no more events are processed. No error is logged,
no run is marked failed.

EVIDENCE:
```python
async def watch(self) -> AsyncGenerator[dict, None]:
    self._stop_event = asyncio.Event()
    try:
        import watchfiles
        async for changes in watchfiles.awatch(self.path, stop_event=self._stop_event):
            # ↑ if watchfiles raises OSError/PermissionError, it propagates uncaught
            for change_type, file_path in changes:
                ...
    except ImportError:
        # polling fallback
```

REPRODUCTION SCENARIO:
Start a `FileWatcherSource` on a directory, then delete the directory while
the watcher is running. `watchfiles.awatch()` raises `FileNotFoundError`.
The exception propagates to `asyncio.gather` which discards it silently.

IMPACT:
Silent event source failure — pipeline appears to be running but no events
are processed. No error is surfaced to the user.

FIX DIRECTION:
Catch non-`ImportError` exceptions from the `watchfiles` path and either
re-raise with context or log and yield a sentinel error event:
```python
except (OSError, RuntimeError) as exc:
    raise RuntimeError(
        f"FileWatcherSource: watchfiles backend failed for path '{self.path}': {exc}"
    ) from exc
```

--------------------------------------------------------------------
FILE:        app/core/events.py
FUNCTION:    FileWatcherSource.watch
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Watch a directory for new or modified files.

WHAT IT ACTUALLY DOES:
The constructor accepts `path` as a string but does NOT validate that the path
exists or is a directory before `watch()` is called. In the polling fallback
path, `os.listdir(self.path)` raises `FileNotFoundError` if the path does not
exist — but this is caught by `except OSError: pass`, so the watcher silently
does nothing. In the `watchfiles` path, `watchfiles.awatch()` raises
`FileNotFoundError` immediately, which propagates uncaught (see finding above).

THE BUG / RISK:
A non-existent or non-directory path causes:
- `watchfiles` path: uncaught exception → silent task failure
- Polling path: `OSError` caught → silent infinite loop doing nothing

In both cases, no error is surfaced to the user.

EVIDENCE:
```python
def __init__(self, path: str, pattern: str = "*", poll_interval_s: float = 1.0) -> None:
    self.path = path   # ← no validation
    ...

# Polling path:
except OSError:
    pass   # ← swallows FileNotFoundError silently
```

REPRODUCTION SCENARIO:
`create_event_source("file_watcher", {"path": "/nonexistent/dir"})` — no error
at construction. `watch()` silently does nothing in polling mode.

IMPACT:
Silent failure — event-driven pipeline runs indefinitely without processing
any events. No error is surfaced.

FIX DIRECTION:
Validate path in `__init__` or at the start of `watch()`:
```python
async def watch(self):
    if not os.path.isdir(self.path):
        raise FileNotFoundError(
            f"FileWatcherSource: path '{self.path}' does not exist or is not a directory"
        )
    ...
```

--------------------------------------------------------------------
FILE:        app/core/events.py
FUNCTION:    FileWatcherSource.watch
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Yield event payloads indefinitely until cancelled via `close()`.

WHAT IT ACTUALLY DOES:
`self._stop_event` is created at the start of `watch()`. If `close()` is
called BEFORE `watch()` is called (e.g., a race condition where the pipeline
is cancelled before the event source starts), `self._stop_event` is `None`
and `close()` does nothing. When `watch()` is subsequently called, it creates
a new `asyncio.Event()` that is never set, so the watcher runs indefinitely.

THE BUG / RISK:
`close()` called before `watch()` is a no-op. The watcher then runs forever
because the stop event is never set.

EVIDENCE:
```python
def __init__(self, ...):
    self._stop_event: asyncio.Event | None = None   # ← None initially

async def close(self) -> None:
    if self._stop_event is not None:
        self._stop_event.set()   # ← no-op if watch() not yet called
```

REPRODUCTION SCENARIO:
Pipeline is cancelled immediately after `create_event_source()` but before
`source.watch()` is called. `close()` is a no-op. When `watch()` eventually
starts, it runs forever.

IMPACT:
Watcher runs indefinitely after pipeline cancellation. Resource leak.

FIX DIRECTION:
Use a pre-created `asyncio.Event` in `__init__`, or track a "closed" flag:
```python
def __init__(self, ...):
    self._closed = False

async def close(self):
    self._closed = True
    if self._stop_event is not None:
        self._stop_event.set()

async def watch(self):
    if self._closed:
        return
    self._stop_event = asyncio.Event()
    ...
```

--------------------------------------------------------------------
FILE:        app/core/events.py
FUNCTION:    TimerSource.watch
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Fire at a configurable interval; `_tick` counts the number of fires.

WHAT IT ACTUALLY DOES:
`self._tick` is an instance variable initialized to 0 in `__init__`. If
`watch()` is called multiple times on the same `TimerSource` instance (e.g.,
after a restart), `_tick` continues from where it left off rather than
resetting to 0. This is probably intentional (monotonic tick counter) but is
not documented.

More importantly, `self._stop_event` is created inside `watch()`. If `watch()`
is called a second time after `close()`, a new `asyncio.Event` is created and
the timer restarts — but `_tick` is not reset. This inconsistency (tick
counter not reset, stop event reset) could confuse consumers that use `tick`
to detect restarts.

THE BUG / RISK:
`_tick` is not reset between `watch()` calls. Consumers that use `tick == 1`
to detect the first fire after a restart will never see `tick == 1` again.

EVIDENCE:
```python
def __init__(self, interval_s: float) -> None:
    self._tick = 0   # ← initialized once, never reset

async def watch(self) -> AsyncGenerator[dict, None]:
    self._stop_event = asyncio.Event()   # ← reset on each watch() call
    while not self._stop_event.is_set():
        ...
        self._tick += 1   # ← continues from prior value
```

REPRODUCTION SCENARIO:
```python
src = TimerSource(interval_s=0.1)
async for event in src.watch():
    if event["tick"] == 3:
        await src.close()
        break
# Restart:
async for event in src.watch():
    print(event["tick"])   # starts at 4, not 1
```

IMPACT:
Confusing tick values after restart. Low functional impact but poor
observability.

FIX DIRECTION:
Document that `_tick` is monotonic and not reset between calls, or reset it
at the start of `watch()`.

--------------------------------------------------------------------
FILE:        app/core/events.py
FUNCTION:    create_event_source
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Instantiate an EventSource by type name; raises `ValueError` if source_type
is not registered or source_config contains unknown keys.

WHAT IT ACTUALLY DOES:
The `QueueSource` constructor takes `queue: asyncio.Queue` as its only
parameter. `create_event_source("queue", {"queue": my_queue})` would work
correctly. However, `asyncio.Queue` objects cannot be serialized to JSON or
passed via the IR's `source_config` dict (which is loaded from JSON). The
`queue` parameter must be a live Python object, but the IR stores
`source_config` as a plain dict of JSON-serializable values.

THE BUG / RISK:
`QueueSource` cannot be instantiated via `create_event_source()` from an IR
`event_trigger` config because `asyncio.Queue` is not JSON-serializable. Any
attempt to use `source_type: "queue"` in an IR will fail with a `TypeError`
when `cls(**source_config)` is called with a dict value for `queue` instead
of an `asyncio.Queue` instance.

EVIDENCE:
```python
class QueueSource(EventSource):
    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue   # ← requires live asyncio.Queue object

# In create_event_source:
return cls(**source_config)   # ← source_config["queue"] would be a dict/str from JSON
```

REPRODUCTION SCENARIO:
IR with `event_trigger: {source_type: "queue", source_config: {queue: "my_queue"}}`.
`create_event_source("queue", {"queue": "my_queue"})` → `TypeError` because
`QueueSource.__init__` expects `asyncio.Queue`, not `str`.

IMPACT:
`QueueSource` is effectively unusable via the IR/event_trigger mechanism.
Only usable when constructed directly in Python code.

FIX DIRECTION:
Document that `QueueSource` must be constructed directly (not via
`create_event_source`) and remove it from `_SOURCE_REGISTRY`, or add a
queue registry that maps string names to live `asyncio.Queue` instances.

--------------------------------------------------------------------
FILE:        app/core/events.py
FUNCTION:    FileWatcherSource.watch (polling path)
CATEGORY:    Performance
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Poll the directory at `poll_interval_s` intervals for new or modified files.

WHAT IT ACTUALLY DOES:
The polling path calls `os.listdir(self.path)` and `os.path.getmtime(fpath)`
for every file on every poll interval. For directories with many files (e.g.,
a streaming audio chunk directory with thousands of files), this is O(n) per
poll interval. With `poll_interval_s=1.0` and 10,000 files, this is 10,000
`stat()` calls per second.

THE BUG / RISK:
No upper bound on directory size. High-frequency polling of large directories
can saturate I/O.

EVIDENCE:
```python
for fname in os.listdir(self.path):   # ← O(n) per interval
    ...
    mtime = os.path.getmtime(fpath)   # ← one stat() per file
```

REPRODUCTION SCENARIO:
Directory with 10,000 files, `poll_interval_s=0.1`. 100,000 `stat()` calls
per second.

IMPACT:
I/O saturation on large directories with short poll intervals. Low risk for
typical use cases.

FIX DIRECTION:
Document the performance characteristic and recommend `watchfiles` for
production use. Optionally add a `max_files` guard.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `FileWatcherSource` silently stops yielding events when the watched directory is deleted or becomes inaccessible — the watcher task fails silently and the pipeline continues running without processing any events |
