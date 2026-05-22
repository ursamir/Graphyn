# Backend Services Review

**Date:** 2026-05-18  
**Files:** `run_manager.py`, `logger.py`, `artifact_store.py`, `provenance.py`, `config.py`, `quality_checker.py`, `webhook.py`, `ingestion.py`, `project_manager.py`, `registry_runtime.py`, `runtime_backend.py`

---

## `run_manager.py`

### B-01 🔴 `_artifacts` list has no lock — parallel wave execution causes corruption
`RunManager._artifacts` is a plain `list`. In parallel wave execution, multiple nodes call `register_artifact()` concurrently from different threads. Python's GIL does not protect `list.append()` from interleaving at the C level in all cases, and the surrounding logic (hash computation, store write) is definitely not atomic.

```python
# In register_artifact() — called concurrently from ParallelExecutor threads
self._artifacts.append(record)   # ← no lock
```

**Fix:**
```python
self._artifacts_lock = threading.Lock()

def register_artifact(self, ...):
    ...
    with self._artifacts_lock:
        self._artifacts.append(record)
    return record
```

---

### B-02 🟠 `run_id` is only 8 hex characters — collision risk
```python
self.run_id = str(uuid.uuid4())[:8]
```
8 hex characters = 32 bits of entropy. With ~65,000 runs the collision probability exceeds 50% (birthday paradox). For high-throughput systems this is a real risk that causes run data to be silently overwritten.

**Fix:** Use at least 16 characters, or the full UUID:
```python
self.run_id = str(uuid.uuid4())   # or [:16] as a compromise
```

---

### B-03 🟠 `_write_meta` uses system default encoding
```python
with open(path, "w") as f:   # ← no encoding specified
    json.dump(data, f, indent=2)
```
On Windows or non-UTF-8 systems this can corrupt metadata containing non-ASCII characters (e.g. file paths with Unicode).

**Fix:** Always specify `encoding="utf-8"`:
```python
with open(path, "w", encoding="utf-8") as f:
```
This applies to `save_config()`, `save_logs()`, `update_resume_state()`, `init_resume_state()`, and `mark_failed()` as well.

---

### B-04 🟠 `_write_meta_field` is not thread-safe — lost update race
```python
def _write_meta_field(self, key: str, value: str) -> None:
    # read
    with open(meta_path) as f:
        existing = json.load(f)
    # ← another thread can write here
    existing[key] = value
    # write
    self._write_meta(existing)
```
`pause()` and `cancel()` both call `_write_meta_field`. If called concurrently, one update is silently lost. `RunManager` has no instance-level lock.

**Fix:** Add `self._meta_lock = threading.Lock()` and wrap all `_write_meta*` calls.

---

### B-05 🟠 `_ACTIVE_RUNS` module-level dict is not thread-safe
```python
_ACTIVE_RUNS: dict[str, "RunManager"] = {}

def register_active_run(run): _ACTIVE_RUNS[run.run_id] = run
def deregister_active_run(run_id): _ACTIVE_RUNS.pop(run_id, None)
```
Concurrent `register_active_run` / `deregister_active_run` calls from different threads (e.g. multiple concurrent API requests) can corrupt the dict.

**Fix:**
```python
_ACTIVE_RUNS_LOCK = threading.Lock()

def register_active_run(run):
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS[run.run_id] = run
```

---

### B-06 🟡 `find_latest_checkpoint` uses `os.listdir` — not sorted by mtime
The sort key is `created_at` string from `meta.json`. If `meta.json` is missing or corrupt, `created_at` is `""` and the sort places that run first (lexicographically smallest). The wrong checkpoint is then loaded silently.

**Fix:** Fall back to directory `mtime` when `created_at` is missing:
```python
mtime = os.path.getmtime(os.path.join(runs_dir_path, run_dir_name))
candidates.append((created_at or str(mtime), checkpoint_dir))
```

---

### B-07 🔵 `compute_graph_hash` and `save_graph_ir` both compute the same hash independently
`save_graph_ir()` computes `self._graph_hash` from `graph_data`. `compute_graph_hash()` is a `@staticmethod` that takes a `GraphIR` object and calls `dump_ir()` again. They can produce different hashes if `dump_ir()` is not deterministic (key ordering). Both should use the same code path.

---

## `logger.py`

### B-08 🟠 `_emit` vs `_emit_structured` inconsistency — structured events invisible in Python logs
`_emit` appends to `self.logs` AND writes to Python's `logging` module. `_emit_structured` appends to `self.logs` and the queue but does NOT write to Python's `logging`. This means `node_start`, `node_end`, `pipeline_summary` etc. are invisible in log files unless the queue is consumed.

**Recommendation:** Either route all events through `_emit` (with a structured format), or document this split clearly so operators know to consume the queue for full observability.

---

### B-09 🟠 `self.logs` is an unbounded list
For long-running pipelines with thousands of nodes, `self.logs` grows indefinitely. In a server process that handles many pipeline runs, this is a memory leak.

**Fix:** Cap the list at a configurable max size (e.g. 10,000 entries) with a ring-buffer or deque:
```python
from collections import deque
self.logs = deque(maxlen=10_000)
```

---

### B-10 🟡 Inconsistent duration key: `"duration"` vs `"duration_s"`
`node_end` emits `"duration": duration` but `pipeline_done`, `wave_end`, and `pipeline_summary` use `"duration_s"`. Consumers of the event stream must handle both keys.

**Fix:** Standardize on `"duration_s"` everywhere and update `node_end`:
```python
self._emit_structured({
    "type": "node_end",
    ...
    "duration_s": duration,   # was "duration"
    ...
})
```

---

### B-11 🔵 `summary()` does not emit a structured event
`summary()` calls `self.info()` (plain text log) but does not emit a structured event to the queue. Callers expecting a `"summary"` event type in the queue won't find it. `pipeline_summary()` is the structured equivalent but they are separate methods with no connection.

---

## `artifact_store.py`

### B-12 🟠 `list()` performs a full directory scan on every call
```python
for entry in self.base.iterdir():
    ...
```
O(N) filesystem scan for every `list()` call. The `index.json` maps `content_hash → artifact_id` but there is no index by `run_id`, `node_type`, or `artifact_type`. Filtering requires loading every `record.json`.

**Fix:** Maintain a secondary index (e.g. `by_run/{run_id}.json`) similar to `ProvenanceStore`.

---

### B-13 🟠 `_compute_content_hash` for `audio_samples` does not hash audio data
```python
manifest_entries.append({
    "path": path, "sample_rate": sr, "shape": list(shape), "label": label
})
```
Two different audio files with the same path, sample rate, shape, and label produce the same content hash. This causes false deduplication — the second file is silently treated as identical to the first.

**Fix:** Include a hash of the actual PCM data:
```python
import hashlib
data_hash = hashlib.sha256(sample.data.tobytes()).hexdigest()[:16]
manifest_entries.append({..., "data_hash": data_hash})
```

---

### B-14 🟠 `artifact_id` is only 8 hex characters — same collision risk as `run_id`
See B-02. With many artifacts the birthday paradox applies. Use at least 16 characters.

---

### B-15 🟡 `_serialize_json` imports numpy unconditionally at function entry
```python
def _serialize_json(self, data, data_dir):
    import numpy as np   # ← raises ImportError if numpy not installed
```
This will raise `ImportError` for non-numpy data on systems without numpy installed, even though numpy is not needed for that data.

**Fix:**
```python
try:
    import numpy as np
    _has_numpy = True
except ImportError:
    _has_numpy = False
```

---

### B-16 🔵 `get_versions` calls `self.list()` — full scan for a name filter
```python
def get_versions(self, artifact_name: str) -> list[ArtifactRecord]:
    return [r for r in self.list() if r.name == artifact_name]
```
Full directory scan just to filter by name. Should maintain a `by_name/` index.

---

## `provenance.py`

### B-17 🟠 `get_lineage` is recursive — unbounded recursion depth
```python
def get_lineage(self, artifact_id, _visited=None):
    ...
    inputs = [self.get_lineage(input_id, _visited) for input_id in prov.input_artifact_ids]
```
A very deep lineage chain (e.g. 1000 sequential nodes) will hit Python's default recursion limit of 1000 and raise `RecursionError`.

**Fix:** Convert to an iterative BFS/DFS with an explicit stack:
```python
def get_lineage(self, artifact_id: str) -> dict:
    visited = set()
    stack = [(artifact_id, None)]  # (id, parent_node)
    ...
```

---

### B-18 🟡 `find_reproducible` scans all `*.json` files — no graph_hash index
```python
for entry in self.base.iterdir():
    if not entry.is_file() or entry.suffix != ".json":
        continue
    ...
    if record.graph_hash == graph_hash:
        records.append(record)
```
O(N) scan of the entire provenance directory for every reproducibility query.

**Fix:** Maintain a `by_graph_hash/{hash[:16]}.json` index file, similar to `by_run/`.

---

### B-19 🟡 `record()` silently overwrites existing provenance records
If the same `artifact_id` is recorded twice (e.g. due to a retry or duplicate registration), the second write overwrites the first without warning. The `by_run` list deduplicates correctly, but the record itself is silently replaced.

**Fix:** Check for existence before writing and log a warning if overwriting:
```python
if record_path.exists():
    log.warning("ProvenanceStore: overwriting existing record for artifact %s", artifact_id)
```

---

## `config.py`

### B-20 🔴 `plugins_home()` returns CWD-relative path — inconsistent with `plugin_registry_path()`
```python
def plugins_home() -> Path:
    return Path(_env("GRAPHYN_PLUGINS_DIR", default="plugins"))
    # Returns Path("plugins") — relative to CWD

def plugin_registry_path() -> Path:
    return graphyn_home() / "plugins" / "registry.json"
    # Returns ~/.graphyn/plugins/registry.json — absolute
```
Plugin packages are installed to `./plugins/` (CWD-relative) but the registry that tracks them lives in `~/.graphyn/plugins/registry.json`. If the CWD changes between runs, `plugins_home()` resolves to a different directory while the registry still points to the old location. This is a **split-brain** configuration.

**Fix:** Either:
- Make `plugins_home()` return `graphyn_home() / "plugins"` (consistent with registry), or
- Document explicitly that `GRAPHYN_PLUGINS_DIR` is always resolved relative to CWD and update the registry path accordingly.

---

### B-21 🔵 No path normalization or security check on env var values
`project_dir()` returns whatever string is in `GRAPHYN_PROJECT_DIR`, including paths with `..` components (e.g. `../../etc`). While this is a configuration value (not user input), it should be normalized:
```python
return Path(_env("GRAPHYN_PROJECT_DIR", default="workspace")).resolve()
```

---

## `quality_checker.py`

### B-22 🟠 `run()` loads all WAV files fully into memory
`_load_audio()` loads the full audio array for every file. For large datasets (thousands of files) this can exhaust memory. Checks like `duration_range` and `sample_rate` only need file metadata, not the full audio data.

**Fix:** Use `soundfile.info()` for metadata-only checks and only load audio data for checks that require it (clipping, dc_offset, snr, duplicates).

---

### B-23 🟡 `_check_snr` assumes silence at the start of every file
The SNR estimate uses the first `noise_profile_ms` milliseconds as the noise floor. For files that start with speech or music, the "noise" estimate is actually signal, producing a meaningless (and misleadingly low) SNR value. This is a fundamental limitation of the approach.

**Fix:** Document this limitation in the docstring and consider using a VAD (Voice Activity Detection) to find actual silence regions.

---

### B-24 🟡 `_check_duplicate` silently skips resampling if librosa is unavailable
```python
try:
    import librosa
    mono = librosa.resample(mono, orig_sr=sr, target_sr=target_sr)
except Exception:
    pass  # Use original if resampling fails
```
Two identical files at different sample rates will not be detected as duplicates when librosa is unavailable. No warning is emitted.

**Fix:** Log a warning when resampling is skipped so operators know duplicate detection is degraded.

---

### B-25 🟡 `_persist` silently fails — caller cannot detect report write failure
```python
except Exception as exc:
    logger.warning("Failed to persist quality_report.json: %s", exc)
```
`run()` returns normally even if the report was not saved. The caller has no way to know the report is missing.

**Fix:** Return a result object that includes a `report_saved: bool` field, or raise the exception.

---

## `webhook.py`

### B-26 🔴 No URL validation — SSRF vulnerability
```python
def save(self, url: str, events: list[str]) -> None:
    config = {"url": url, "events": events}
    with self.CONFIG_PATH.open("w", ...) as f:
        json.dump(config, f, ...)
```
Any string is accepted as `url`. A misconfigured or malicious URL (e.g. `file:///etc/passwd`, `http://169.254.169.254/` AWS metadata endpoint, `http://localhost:6379/` Redis) will be POSTed to in a background thread.

**Fix:**
```python
from urllib.parse import urlparse

def save(self, url: str, events: list[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Webhook URL must use http or https scheme, got: {parsed.scheme!r}")
    if not parsed.netloc:
        raise ValueError(f"Webhook URL must have a valid host: {url!r}")
```

---

### B-27 🟠 `notify()` reads `webhooks.json` from disk on every call
For high-frequency events (node_start + node_end per node, per pipeline run), this is many disk reads. For a 10-node pipeline: 20 disk reads per run.

**Fix:** Cache the config in memory and invalidate on `save()`:
```python
self._config_cache: dict | None = None

def save(self, url, events):
    ...
    self._config_cache = None  # invalidate

def notify(self, event, payload):
    if self._config_cache is None:
        self._config_cache = self.load()
    config = self._config_cache
    ...
```

---

### B-28 🟡 Background thread is daemon=True — notifications silently dropped on exit
If the process exits before the background thread completes the HTTP POST, the notification is silently dropped. No retry, no queue, no delivery guarantee. This is acceptable for fire-and-forget but should be documented.

---

## `ingestion.py`

### B-29 🟠 `_jobs` module-level dict is never cleaned up — memory leak
```python
_jobs: dict[str, "IngestionJob"] = {}
```
Completed jobs accumulate indefinitely. In a long-running server process this is a memory leak. Each `IngestionJob` holds a list of all progress events, which can be large for big datasets.

**Fix:** Add a TTL-based cleanup or a max-jobs limit:
```python
MAX_JOBS = 1000
if len(_jobs) >= MAX_JOBS:
    # Remove oldest completed jobs
    ...
```

---

### B-30 🟡 `IngestionJob` uses `object.__getattribute__` to access `_lock` — design smell
`IngestionJob` is a Pydantic `BaseModel` but needs a `threading.Lock` as non-field state. The workaround uses `object.__getattribute__` and `object.__setattr__` to bypass Pydantic's field access.

**Fix:** `IngestionJob` should not be a `BaseModel`. Use a plain dataclass or a regular class with `__slots__`:
```python
@dataclass
class IngestionJob:
    job_id: str
    status: str
    progress: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
```

---

### B-31 🟡 TOCTOU race in `_save_hf_audio_sample` filename uniqueness check
```python
dest_path = dest_dir / filename
if dest_path.exists():
    dest_path = dest_dir / f"sample_{index:06d}_{uuid.uuid4().hex[:6]}.wav"
```
Between the `exists()` check and the `sf.write()` call, another thread could create the same file. The UUID suffix fallback only triggers on the first collision check.

**Fix:** Use `tempfile.NamedTemporaryFile` or always include a UUID in the filename.

---

## `project_manager.py`

### B-32 🟠 `_now()` uses deprecated `datetime.utcnow()`
```python
@staticmethod
def _now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"
```
`datetime.utcnow()` is deprecated since Python 3.12 and will be removed in a future version. It also produces a naive datetime (no timezone info).

**Fix:**
```python
from datetime import datetime, timezone
return datetime.now(timezone.utc).isoformat()
```

---

### B-33 🟡 `restore_version` and `restore_snapshot` have no rollback on partial failure
Both methods copy files from a source directory to the project root. If the copy fails midway (disk full, permission error), the project is left in a partially-restored state with no recovery path.

**Fix:** Copy to a temp directory first, then atomically swap:
```python
tmp_dir = d.parent / f".restore_tmp_{uuid.uuid4().hex[:8]}"
shutil.copytree(str(version_dir), str(tmp_dir))
# Only swap after successful copy
shutil.move(str(tmp_dir), str(d))
```

---

### B-34 🟡 `_estimate_snr` silently returns `20.0` for non-16-bit WAV files
```python
if sampwidth != 2:
    return 20.0  # fallback for non-16-bit
```
24-bit and 32-bit WAV files (common in professional audio) silently return a hardcoded SNR of 20 dB. The `get_stats()` SNR histogram will be misleading for projects with high-bit-depth audio.

**Fix:** Support 24-bit and 32-bit PCM, or log a warning when the fallback is used.

---

### B-35 🔵 `get_stats` opens each WAV file twice — once for duration, once for sample rate
```python
dur = self._wav_duration_s(wav)    # opens wav file
sr = self._wav_sample_rate(wav)    # opens wav file again
```
Each `wave.open()` call is a separate file open. For large datasets this doubles the I/O.

**Fix:** Combine into a single helper:
```python
def _wav_info(self, wav_path: Path) -> tuple[float, int]:
    with wave.open(str(wav_path), "rb") as wf:
        return wf.getnframes() / wf.getframerate(), wf.getframerate()
```

---

## `runtime_backend.py`

### B-36 🟡 `LocalPythonBackend` is not truly stateless
The docstring on `RuntimeBackend` states "implementations MUST be stateless" but `LocalPythonBackend.execute()` calls `run_pipeline_ir()` which creates a `RunManager` internally if none is provided. The `RunManager` is stateful (creates directories, writes files). The backend itself is stateless but its side effects are not.

**Fix:** Clarify the docstring: "the backend instance is stateless; each `execute()` call creates its own `RunManager`."

---

### B-37 🔵 `get_backend()` instantiates a new backend on every call
```python
def get_backend(backend_id: str = "local_python") -> RuntimeBackend:
    return _BACKEND_REGISTRY[backend_id]()
```
Fine for `LocalPythonBackend` but could be expensive for future backends that hold connections (e.g. `DockerBackend`, `KubernetesBackend`). Consider a singleton pattern or a factory that caches instances.
