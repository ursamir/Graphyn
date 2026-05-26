# Functional Review — PluginPackage/Audio/speech_synthesizer/nodes.py

**Group:** 15 — Audio Plugins Batch 3
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speech_synthesizer/nodes.py
FUNCTION:    SpeechSynthesizerNode._synthesize_espeak
CATEGORY:    Resource Leak
SEVERITY:    CRITICAL
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Synthesize speech via eSpeak NG subprocess → WAV → numpy.

WHAT IT ACTUALLY DOES:
The function creates TWO temporary files but only deletes the second one.
The first `NamedTemporaryFile` (created at the top of the function) is never
deleted:

```python
with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    out_path = f.name   # ← first temp file, path assigned to out_path

cmd = ["espeak-ng", ..., "-w", out_path, text]

with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    out_path = f.name   # ← second temp file OVERWRITES out_path
```

The `cmd` list is built with the first `out_path`, but then `out_path` is
immediately overwritten by the second `NamedTemporaryFile`. So:
1. eSpeak writes to the first temp file path.
2. The `finally` block deletes the second temp file (which is empty/unused).
3. The first temp file (containing the actual audio) is NEVER deleted.
4. The audio is read from the second temp file (which is empty) — `sf.read`
   or `wave.open` will fail or return empty audio.

EVIDENCE:
```python
# Line ~175
with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    out_path = f.name   # first temp file

cmd = [
    "espeak-ng",
    "-v", self.config.language,
    "-s", str(int(175 * self.config.speed)),
    "-w", out_path,     # espeak writes here (first temp file)
    text,
]

with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    out_path = f.name   # OVERWRITES out_path with second temp file

try:
    result = subprocess.run(cmd, ...)  # writes to first temp file
    ...
finally:
    Path(out_path).unlink(missing_ok=True)  # deletes second (empty) temp file
    # first temp file is NEVER deleted → resource leak
```

REPRODUCTION SCENARIO:
Call `_synthesize_espeak("hello")`. eSpeak writes audio to temp file #1.
`sf.read(out_path)` reads temp file #2 (empty) → raises or returns empty array.
Temp file #1 leaks on disk.

IMPACT:
1. **Data loss** — synthesized audio is never read; function returns empty or
   raises an exception.
2. **Resource leak** — temp file #1 accumulates on disk with every call.
3. **Crash** — `sf.read` on an empty WAV file raises `SoundFileError`.

FIX DIRECTION:
Remove the duplicate `NamedTemporaryFile` block. The function should create
exactly one temp file:
```python
with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    out_path = f.name

cmd = ["espeak-ng", "-v", self.config.language,
       "-s", str(int(175 * self.config.speed)),
       "-w", out_path, text]
try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"eSpeak NG failed: {result.stderr}")
    import soundfile as sf
    audio_data, sr = sf.read(out_path, dtype="float32")
finally:
    Path(out_path).unlink(missing_ok=True)
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speech_synthesizer/nodes.py
FUNCTION:    SpeechSynthesizerNode._synthesize_coqui
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Synthesize speech using Coqui TTS; caches the TTS model in `self._tts_model`.

WHAT IT ACTUALLY DOES:
`if not hasattr(self, "_tts_model"): self._tts_model = TTS(...)` — the model
is loaded lazily on the first call to `_synthesize_coqui`. However, `setup()`
is never defined for this node, so the model is not pre-loaded during the
setup phase. This means:
1. The first call to `process()` incurs model load latency (potentially
   minutes for large TTS models).
2. If `TTS(model_name=...)` raises (e.g. model not found, network error),
   the exception propagates out of `process()` mid-execution, leaving
   `self._tts_model` unset. The next call will attempt to load again.
3. There is no thread safety — if two threads call `process()` simultaneously
   on the same node instance, both may attempt to load the model concurrently.

EVIDENCE:
```python
def _synthesize_coqui(self, text: str) -> tuple[np.ndarray, int]:
    ...
    if not hasattr(self, "_tts_model"):
        self._tts_model = TTS(model_name=self.config.model_name, progress_bar=False)
```

REPRODUCTION SCENARIO:
Call `process()` with an invalid `model_name`. `TTS(...)` raises. Next call
retries the load. In concurrent use, two threads both enter the `if not hasattr`
branch simultaneously.

IMPACT:
Repeated model load attempts on failure; potential race condition in concurrent
use; no setup-time validation of model availability.

FIX DIRECTION:
Implement `setup()` to pre-load the model:
```python
def setup(self) -> None:
    backend = self._resolve_backend()
    if backend == "coqui":
        from TTS.api import TTS
        self._tts_model = TTS(model_name=self.config.model_name, progress_bar=False)
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speech_synthesizer/nodes.py
FUNCTION:    SpeechSynthesizerNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Accept a list of text strings and produce a list of AudioSample objects.

WHAT IT ACTUALLY DOES:
`_resolve_backend()` is called once per `process()` invocation, which re-runs
the import check on every call. For the `auto` backend, this means attempting
`from TTS.api import TTS` on every call — a non-trivial import cost.

More importantly, `_resolve_backend()` is called inside `process()` without
caching. If the backend changes between calls (impossible with immutable config,
but the pattern is fragile), the model loaded in `_synthesize_coqui` may not
match the resolved backend.

Additionally, `texts` is typed as `list` (unparameterised). If a caller passes
a list of non-string objects (e.g. `[None, 42]`), `str(text).strip()` converts
them silently. `str(None)` = `"None"` which will be synthesized as the word
"None". This is a silent wrong result.

EVIDENCE:
```python
def process(self, texts: list) -> list[AudioSample]:
    backend = self._resolve_backend()  # re-runs import check every call
    for i, text in enumerate(texts):
        text_str = str(text).strip()  # str(None) = "None" — silent wrong result
```

REPRODUCTION SCENARIO:
Pass `[None, "hello"]` — synthesizes "None" as speech without warning.

IMPACT:
Silent wrong result for None inputs; repeated import overhead per call.

FIX DIRECTION:
```python
if not isinstance(text, str):
    log.warning("SpeechSynthesizerNode: non-string input at index %d (%r) — skipping", i, text)
    continue
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speech_synthesizer/nodes.py
FUNCTION:    SpeechSynthesizerNode._synthesize_espeak
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Synthesize via eSpeak NG subprocess → WAV → numpy.

WHAT IT ACTUALLY DOES:
(Beyond the CRITICAL resource leak above.) The `subprocess.run` call has a
`timeout=30` seconds. If eSpeak hangs (e.g. waiting for audio device), the
`subprocess.TimeoutExpired` exception is not caught. It propagates out of
`process()` without cleaning up the temp file (the `finally` block only runs
for the inner `try`, but `subprocess.run` is outside the `try` block).

Wait — re-reading: `subprocess.run` IS inside the outer `try` block (the one
with the `finally`). So the temp file IS cleaned up on timeout. However,
`subprocess.TimeoutExpired` propagates to the caller with no context about
which text caused the timeout.

EVIDENCE:
```python
try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"eSpeak NG failed: {result.stderr}")
except FileNotFoundError:
    raise ImportError(...)
# TimeoutExpired not caught — propagates as-is
```

IMPACT:
`subprocess.TimeoutExpired` propagates with no context. Caller sees an
unexpected exception type.

FIX DIRECTION:
```python
except subprocess.TimeoutExpired:
    raise RuntimeError(
        f"SpeechSynthesizerNode: eSpeak NG timed out after 30s for text: {text[:50]!r}"
    )
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speech_synthesizer/nodes.py
FUNCTION:    SpeechSynthesizerNode._synthesize_coqui
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write TTS output to a temp file, read it, then delete the temp file.

WHAT IT ACTUALLY DOES:
The temp file is created with `delete=False` and deleted in a `finally` block.
If `self._tts_model.tts_to_file(**kwargs)` raises an exception, the `finally`
block runs and deletes the (possibly empty) temp file. This is correct.

However, if `sf.read(out_path)` raises (e.g. TTS wrote a corrupt file), the
`finally` block still runs and deletes the file. The exception propagates
correctly. This is safe.

The actual risk: `self._tts_model.tts_to_file` may write to `out_path` and
then the process is killed (SIGKILL). The temp file leaks. This is an
unavoidable limitation of the temp-file pattern with `delete=False`.

No code change needed — this is an inherent limitation, not a bug.

EVIDENCE:
```python
with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    out_path = f.name
try:
    self._tts_model.tts_to_file(**kwargs)
    audio_data, sr = sf.read(out_path, dtype="float32")
finally:
    Path(out_path).unlink(missing_ok=True)
```

IMPACT:
Temp file leaks only on SIGKILL. Acceptable.

FIX DIRECTION:
No change needed. Document the limitation.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | CRITICAL |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | `_synthesize_espeak` has a duplicate NamedTemporaryFile bug — eSpeak writes to temp file #1 but the code reads from temp file #2 (empty), causing data loss and a temp file leak on every call |
