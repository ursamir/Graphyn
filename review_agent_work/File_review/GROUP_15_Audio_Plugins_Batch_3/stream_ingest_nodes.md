# Functional Review — PluginPackage/Audio/stream_ingest/nodes.py

**Group:** 15 — Audio Plugins Batch 3
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/stream_ingest/nodes.py
FUNCTION:    StreamIngestNode._capture_websocket
CATEGORY:    Async Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Connect to a WebSocket URL and receive `buffer_size` chunks of raw float32 PCM.

WHAT IT ACTUALLY DOES:
Uses `asyncio.run(_receive())` to run the async WebSocket receiver. This works
correctly when called from a synchronous context. However, if `process()` is
called from within an already-running event loop (e.g. from an async pipeline
executor, Jupyter notebook, or FastAPI endpoint), `asyncio.run()` raises
`RuntimeError: This event loop is already running`.

EVIDENCE:
```python
return asyncio.run(_receive())
# RuntimeError if called from within an existing event loop
```

REPRODUCTION SCENARIO:
```python
import asyncio
async def test():
    node = StreamIngestNode(config=StreamIngestNode.Config(
        source="websocket", websocket_url="ws://localhost:8765"))
    node.process({})  # asyncio.run() raises RuntimeError
asyncio.run(test())
```

IMPACT:
Crash when used in any async context (FastAPI, async pipeline executor,
Jupyter). The platform's async executor would trigger this.

FIX DIRECTION:
Use `nest_asyncio` or detect the running loop:
```python
try:
    loop = asyncio.get_running_loop()
    # Already in async context — use run_coroutine_threadsafe or nest_asyncio
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(asyncio.run, _receive())
        return future.result()
except RuntimeError:
    return asyncio.run(_receive())
```
Or better: make `process()` async and `await _receive()` directly.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/stream_ingest/nodes.py
FUNCTION:    StreamIngestNode._capture_microphone
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Capture `duration_s` seconds from a local microphone via sounddevice.

WHAT IT ACTUALLY DOES:
`sd.rec(...)` starts a recording. `sd.wait()` blocks until complete. If
`sd.wait()` is interrupted (e.g. KeyboardInterrupt, thread cancellation),
the recording stream is not explicitly stopped. sounddevice may leave the
audio device in an open state.

Additionally, `sd.rec()` with `channels > 1` returns a 2D array of shape
`(N, channels)`. The code does `recording.mean(axis=1)` for multi-channel,
which is correct. But if `channels == 1`, `recording` has shape `(N, 1)` and
`recording.flatten()` produces a 1D array — correct. This is safe.

The real issue: no timeout handling. If the microphone device is unavailable
or `sd.wait()` hangs (e.g. device disconnected mid-recording), the call blocks
indefinitely.

EVIDENCE:
```python
recording = sd.rec(int(duration * sr), samplerate=sr, channels=channels,
                   device=device, dtype="float32")
sd.wait()  # blocks indefinitely if device hangs
```

REPRODUCTION SCENARIO:
Disconnect the audio device mid-recording. `sd.wait()` hangs indefinitely.

IMPACT:
Pipeline hangs indefinitely. No timeout or cancellation mechanism.

FIX DIRECTION:
```python
sd.wait(timeout=duration + 5.0)  # sounddevice wait supports timeout
```
Or wrap in a thread with a timeout.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/stream_ingest/nodes.py
FUNCTION:    StreamIngestNode._stream_file
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Stream a local audio file in chunk_ms chunks via librosa.

WHAT IT ACTUALLY DOES:
`file_path = self.config.file_path or self.config.websocket_url` — falls back
to `websocket_url` for backward compatibility. If neither is set, raises
`ValueError` (correct). However, if `file_path` points to a non-existent file,
`librosa.load()` raises `FileNotFoundError` with a librosa-internal traceback
that does not mention the config field name, making it hard to diagnose.

More importantly: `for i in range(0, len(y) - chunk_samples + 1, chunk_samples)`
— if `len(y) < chunk_samples` (file shorter than one chunk), the range is empty
and the function returns `[]` with no warning. The entire file is silently
discarded.

EVIDENCE:
```python
chunk_samples = int(sr * self.config.chunk_ms / 1000)
for i in range(0, len(y) - chunk_samples + 1, chunk_samples):
    # silent empty range if len(y) < chunk_samples
```

REPRODUCTION SCENARIO:
Pass a 50ms audio file with `chunk_ms=100`. Returns `[]` with no log.

IMPACT:
Silent data loss — files shorter than one chunk are silently discarded.

FIX DIRECTION:
```python
if len(y) < chunk_samples:
    log.warning("StreamIngestNode: file '%s' (%d samples) shorter than "
                "chunk_ms=%d (%d samples) — no chunks produced",
                file_path, len(y), self.config.chunk_ms, chunk_samples)
    return []
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/stream_ingest/nodes.py
FUNCTION:    StreamIngestNode._capture_websocket (inner _receive)
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Receive `buffer_size` chunks of raw float32 PCM bytes from a WebSocket.

WHAT IT ACTUALLY DOES:
`np.frombuffer(message, dtype=np.float32).copy()` — if `len(message)` is not
a multiple of 4 bytes, `np.frombuffer` raises `ValueError: buffer size must
be a multiple of element size`. This exception is not caught and propagates
out of the async function, through `asyncio.run()`, and out of `process()`.

EVIDENCE:
```python
if isinstance(message, bytes):
    data = np.frombuffer(message, dtype=np.float32).copy()
    # ValueError if len(message) % 4 != 0
```

REPRODUCTION SCENARIO:
WebSocket server sends a partial frame (e.g. 3 bytes). `np.frombuffer` raises
`ValueError`.

IMPACT:
Crash on malformed WebSocket messages. No error recovery — the connection is
not closed gracefully.

FIX DIRECTION:
```python
if len(message) % 4 != 0:
    log.warning("StreamIngestNode: WebSocket message length %d not a multiple "
                "of 4 — skipping malformed frame", len(message))
    continue
data = np.frombuffer(message, dtype=np.float32).copy()
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/stream_ingest/nodes.py
FUNCTION:    StreamIngestNode.process
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Source node — multi-port signature (no input ports).

WHAT IT ACTUALLY DOES:
`process(self, inputs: dict) -> dict` — the `inputs` parameter is typed as
`dict` but is never validated or used. If the node executor passes `None`
instead of `{}`, the function proceeds without error (inputs is never accessed).
This is safe but the type annotation is misleading — the base class SISO
shorthand is not used here, which is correct for a source node.

No bug, but the `inputs` parameter could be annotated as `dict | None` for
clarity.

EVIDENCE:
```python
def process(self, inputs: dict) -> dict:
    """Source node — multi-port signature (no input ports)."""
    source = self.config.source
    # inputs is never used
```

IMPACT:
No functional impact. Minor type annotation imprecision.

FIX DIRECTION:
No code change required. Optionally annotate as `inputs: dict | None = None`.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | `asyncio.run()` in `_capture_websocket` crashes when called from an async context (FastAPI, async executor) |
