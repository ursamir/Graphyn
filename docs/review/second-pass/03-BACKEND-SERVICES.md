# G3 Backend Services — Second-Pass Code Review

**Module group:** `app/core/` — Backend Services  
**Reviewer:** Kiro AI  
**Date:** 2025-07-14  
**Files reviewed:** 11  

---

## Part 1 — Exploration Plan

| # | File | Stated Purpose | Key Review Questions |
|---|------|---------------|----------------------|
| 1 | `run_manager.py` | Manages per-run lifecycle: directories, metadata, pause/cancel, artifacts, provenance. | Is `_artifacts` list access thread-safe (B-01)? Is `register_artifact()` locked? Is `update_resume_state()` atomic? Does `find_latest_checkpoint()` have path-traversal risk? |
| 2 | `logger.py` | Structured in-memory pipeline event logger with optional queue streaming. | Is the `deque` bounded (B-09)? Are `_emit` vs `_emit_structured` paths consistent? Is `summary()` idempotent? |
| 3 | `artifact_store.py` | Content-addressed artifact registry; stores typed metadata + serialized data. | Is the `_lock` held across the full read-modify-write cycle? Is deduplication correct? Is `get_versions()` O(N) scan acceptable? |
| 4 | `provenance.py` | Stores and queries artifact lineage records. | Is `record()` thread-safe for concurrent calls on the same artifact (B-13)? Is cycle detection correct? Is the `by_graph_hash` index consistent? |
| 5 | `config.py` | Centralised env-var and path resolution. | Are all env vars accessed via functions here, not `os.environ` directly? Is `project_dir()` resolved to absolute path? |
| 6 | `quality_checker.py` | Automated audio quality checks (duration, SR, clipping, SNR, duplicates, outliers, class imbalance). | Is the SNR assumption documented? Is the duplicate fingerprint stable across platforms? Are numpy imports guarded? |
| 7 | `webhook.py` | Fire-and-forget HTTP POST notifications with SSRF prevention. | Is the SSRF allowlist (B-26) present and correct? Is the config cache invalidated on `save()`? Is the daemon thread safe? |
| 8 | `ingestion.py` | Downloads audio from URLs or HuggingFace datasets into workspace. | Is the TOCTOU race in `_save_hf_audio_sample` fixed (B-31)? Are there path-traversal risks? Is the job store bounded (B-29)? |
| 9 | `project_manager.py` | Central service for project lifecycle, taxonomy, annotations, versions, stats. | Is `generate_dataset_card()` using deprecated `datetime.utcnow()`? Is `validate_annotations()` correct? Are file writes atomic? |
| 10 | `runtime_backend.py` | Pluggable execution backend abstraction; default `LocalPythonBackend` wraps `run_pipeline_ir`. | Is the singleton cache thread-safe? Is `register_backend()` safe under concurrency? |
| 11 | `registry_runtime.py` | Returns the `NodeRegistry` singleton. | Is this a thin wrapper with no logic? Any import-time side effects? |

---

## Part 2 — Per-File Findings


---

### File 1 — `run_manager.py`

#### D1 — Code Quality & Correctness

No logic errors in the main flow. `_write_meta_field` correctly does a read-modify-write under `_meta_lock`. `update_resume_state()` reads then writes `resume_state.json` **without a lock**, which is a correctness issue under concurrent node completion (see G3-01). `find_latest_checkpoint()` sorts by `created_at` string lexicographically — ISO 8601 strings sort correctly, but a float mtime fallback (`str(mtime)`) will sort incorrectly against ISO strings (see G3-02).

#### D2 — Architecture & Design

The lazy-init pattern for `_artifact_store` and `_provenance_store` is clean. The `_WORKSPACE` monkeypatch shim is a test-only concern leaking into production code; a cleaner approach would be a factory parameter. The `find_latest_checkpoint` method reaches into `app.core.pipeline` for `_load_checkpoint_outputs` — a private function — creating a tight coupling (see G3-03).

#### D3 — Error Handling

`_write_meta` has no exception handling; a disk-full or permission error will propagate uncaught and crash the run. `update_resume_state` silently returns if the file doesn't exist, which is correct, but a JSON parse error on the existing file will raise uncaught (see G3-04). `mark_failed` and `mark_cancelled` swallow JSON parse errors on the existing meta file (correct), but `_write_meta` inside them can still raise.

#### D4 — Performance

`find_latest_checkpoint` calls `os.listdir` on the entire runs directory and reads every `meta.json` — O(N) on total run count. For large deployments this will be slow. No issues elsewhere.

#### D5 — Test Coverage Gaps

`update_resume_state` concurrent-write path is untested. The mtime fallback sort in `find_latest_checkpoint` is untested. `compute_graph_hash` with a non-serializable graph is untested.

#### D6 — Security

`find_latest_checkpoint` constructs a path from `run_dir_name` obtained via `os.listdir` — a symlink in the runs directory could escape the workspace. No sanitization of `run_dir_name` (see G3-05).

#### D7 — Documentation

`save_metadata` docstring lists supported keys but does not document what happens if unknown keys are passed (they are silently merged). `find_latest_checkpoint` does not document the mtime fallback behaviour.

#### D8 — Convention Adherence

All paths go through `app.core.config` functions. No direct `os.environ` access. Naming and import patterns follow project conventions.


---

### File 2 — `logger.py`

#### D1 — Code Quality & Correctness

`_emit` and `_emit_structured` are two separate code paths that both append to `self.logs` and put to `self.queue`. This is correct but the duplication means a future change to one path may not be applied to the other. `summary()` calls both `self.info(...)` (which appends to `logs` via `_emit`) and `_emit_structured(...)` (which also appends to `logs`) — this means every `summary()` call produces **two** entries in `self.logs` for the same event (see G3-06).

#### D2 — Architecture & Design

`PipelineLogger` mixes structured event emission with plain-text logging. The two-path design (`_emit` vs `_emit_structured`) is a mild SRP violation. The `deque` is not thread-safe for concurrent `append` + iteration — Python's GIL makes individual `deque.append` atomic, but `list(self.logs)` in `save_logs` (called from `run_manager`) is not atomic with concurrent appends (see G3-07).

#### D3 — Error Handling

No exception handling in `_emit` or `_emit_structured`. If `self.queue.put(entry)` blocks (full queue), the pipeline thread will stall. No timeout or `put_nowait` guard (see G3-08).

#### D4 — Performance

`deque(maxlen=10_000)` bounds memory correctly (B-09 fix confirmed). No O(N²) patterns.

#### D5 — Test Coverage Gaps

The double-emit in `summary()` is not tested. Queue-full blocking scenario is untested. `pipeline_cancelled` with `nodes_remaining=0` is untested.

#### D6 — Security

No issues found.

#### D7 — Documentation

`_emit_structured` docstring says it writes a DEBUG-level line — correct. `warning()` method has a one-line docstring — adequate. `summary()` does not document the double-emit side effect.

#### D8 — Convention Adherence

No direct `os.environ` access. Naming follows project conventions.


---

### File 3 — `artifact_store.py`

#### D1 — Code Quality & Correctness

The deduplication path in `register()` returns a copy of the existing record stamped with the current `run_id`/`node_id`/`node_type` — correct. However, `_append_by_run` is called only for **new** artifacts; deduplicated artifacts are **not** added to the `by_run` index for the current run (see G3-09). This means `list(run_id=X)` via the fast path will miss deduplicated artifacts for run X.

`get_versions()` calls `self.list()` with no filters, which triggers the full directory scan slow path — O(N) on total artifact count. The docstring acknowledges this but it is a correctness concern for large stores (see G3-10).

#### D2 — Architecture & Design

`_lock` is a single coarse-grained lock covering the entire `register()` critical section including disk I/O (serialization). This is correct for safety but will serialize all concurrent artifact registrations. For parallel wave execution this is a throughput bottleneck (see G3-11).

#### D3 — Error Handling

`_serialize_data` raises `ArtifactSerializationError` on failure, but the `data_dir` may have been partially created before the error. There is no cleanup of the partial `artifact_dir` on serialization failure (see G3-12). A subsequent call with the same content hash will find no `record.json` and re-register, but the orphaned partial directory will remain.

#### D4 — Performance

`list()` with `node_type` or `artifact_type` filters always does a full directory scan. For large artifact stores this is O(N). The `by_run` fast path is O(k). No secondary index for `node_type` or `artifact_type`.

#### D5 — Test Coverage Gaps

The deduplication + `by_run` miss scenario is untested. Partial serialization failure cleanup is untested. `get_versions()` with an empty store is untested.

#### D6 — Security

`artifact_id` is a 16-char UUID hex prefix used as a directory name — no path traversal risk since it is generated internally. `data_path` stored in `record.json` is a relative path constructed internally — no injection risk.

#### D7 — Documentation

`register()` docstring does not mention that deduplicated artifacts are not added to the `by_run` index. `get_versions()` documents the O(N) concern — good.

#### D8 — Convention Adherence

Config accessed via `artifacts_dir()`. No direct `os.environ`. Naming follows conventions.


---

### File 4 — `provenance.py`

#### D1 — Code Quality & Correctness

`record()` is fully thread-safe — the entire read-modify-write for both `{artifact_id}.json` and `by_run/{run_id}.json` is inside `self._lock`. B-13 is confirmed fixed.

`find_reproducible()` has a subtle bug: when the `by_hash_path` exists but reading it raises an exception, `artifact_ids` is set to `None` (typed as `list[str]` via `# type: ignore`) and then the `else` branch is skipped, falling through to the slow-path scan — this is the intended fallback, but the `None` assignment is confusing and the type annotation is wrong (see G3-13).

`_build_lineage_node` uses `frozenset` for ancestor tracking — correct for cycle detection. Diamond DAGs (same artifact reachable via two paths) are handled correctly: the node is visited twice but not flagged as a cycle.

#### D2 — Architecture & Design

`ProvenanceStore` is clean and well-separated. The `by_graph_hash` index uses only the first 16 hex chars as the filename key, with a full-hash double-check on read — correct. The slow-path fallback in `find_reproducible` scans `self.base.iterdir()` which will also pick up `by_run/` and `by_graph_hash/` subdirectories; these are skipped by the `entry.suffix != ".json"` check — correct.

#### D3 — Error Handling

`record()` overwrites an existing `{artifact_id}.json` with a warning log — this is intentional but could silently lose the original provenance if called twice for the same artifact in different runs (see G3-14). `by_run_path.write_text` inside `record()` is not atomic (no tmp+replace pattern) — a crash mid-write corrupts the index (see G3-15).

#### D4 — Performance

`find_reproducible()` slow path is O(N) on all provenance files. The fast path is O(k). `get_lineage()` is O(depth × branching_factor) — acceptable for typical DAGs.

#### D5 — Test Coverage Gaps

The `find_reproducible` fallback when index read raises `None` assignment is untested. Concurrent `record()` calls for the same `artifact_id` are untested. Diamond DAG lineage is untested.

#### D6 — Security

No issues found. All paths are constructed from internal IDs.

#### D7 — Documentation

`record()` documents the overwrite-warning behaviour. `find_reproducible()` documents the fast/slow path. `_build_lineage_node` explains the `frozenset` approach — good.

#### D8 — Convention Adherence

Config accessed via `provenance_dir()`. No direct `os.environ`. Naming follows conventions.


---

### File 5 — `config.py`

#### D1 — Code Quality & Correctness

`project_dir()` calls `.resolve()` — correct, produces an absolute path. `_env()` strips whitespace and falls back to `default` on empty string — correct. All path functions are pure (no side effects). No logic errors found.

#### D2 — Architecture & Design

Clean single-responsibility module. The three-tier model (home / project / source) is well-documented. `plugins_home()` has a comment explaining the previous inconsistency — good. No circular imports.

#### D3 — Error Handling

No error handling needed — these are pure path-construction functions. If `GRAPHYN_HOME` is set to an invalid path, callers will get an `OSError` when they try to use the path — this is acceptable and documented.

#### D4 — Performance

No issues found. All functions are O(1).

#### D5 — Test Coverage Gaps

`project_dir()` with a relative `GRAPHYN_PROJECT_DIR` containing `..` components is not tested (`.resolve()` should handle it). `plugins_home()` with an absolute `GRAPHYN_PLUGINS_DIR` override is not tested.

#### D6 — Security

**Security check result:** All env vars in the codebase are accessed via `config.py` functions, not `os.environ` directly. Confirmed by reviewing all 11 files — no direct `os.environ.get("GRAPHYN_...")` calls outside `config.py`. The `_env()` helper strips whitespace, preventing whitespace-only values from being used as paths.

#### D7 — Documentation

Module docstring is comprehensive — lists all env vars, defaults, and the three-tier model. Individual function docstrings are clear. No issues.

#### D8 — Convention Adherence

No direct `os.environ` access outside the `_env()` helper. Naming follows conventions.


---

### File 6 — `quality_checker.py`

#### D1 — Code Quality & Correctness

`_check_snr` uses `np.mean(audio_data ** 2)` as signal power — this is the mean power of the **entire** file, not just non-silent frames, despite the docstring saying "mean of squared non-silent frames". The docstring acknowledges the VAD limitation but the code comment is misleading (see G3-16).

`_check_duplicate` resamples to 16 kHz mono before hashing — correct for cross-SR comparison. However, if `librosa` is unavailable, the hash is computed on the original-SR mono signal, meaning two files at different sample rates with identical content will **not** be detected as duplicates. The warning log is present but the behaviour is a silent correctness degradation (see G3-17).

`_persist` return type annotation says `None` but the docstring says `report_saved = self._persist(...)` in `run()` — the return value is never used, but the variable assignment in `run()` is misleading (see G3-18).

#### D2 — Architecture & Design

`_load_audio` has a librosa-primary / soundfile-fallback pattern — good resilience. `_wav_info` uses `soundfile.info()` for cheap metadata — correct. The class is stateless (all methods are `@staticmethod` or use `self` only for `BASE`/`_persist`) — clean design.

#### D3 — Error Handling

All individual check methods catch exceptions and return `[]` — correct never-raises contract. `_persist` catches exceptions and logs a warning — correct. `_load_audio` returns `(None, 0)` on failure — handled in `run()`.

#### D4 — Performance

`run()` loads every WAV file fully into memory via `librosa.load()`. For large datasets (thousands of files) this is O(N × file_size) memory. No streaming or batching. The `_check_duplicate` resampling step adds significant CPU cost per file (see G3-19).

#### D5 — Test Coverage Gaps

SNR check with a file that starts with speech (not silence) is untested. Duplicate detection when librosa is unavailable is untested. `_check_outliers` with exactly 2 samples is untested. `_check_class_imbalance` with a single label is untested.

#### D6 — Security

`version_dir.rglob("*.wav")` — no path traversal risk since `version_dir` is constructed from validated project/version names. No external input reaches file paths directly.

#### D7 — Documentation

`_check_snr` docstring has a misleading "non-silent frames" claim that contradicts the implementation. The VAD limitation note is good. `_check_duplicate` should document the cross-SR degradation when librosa is absent.

#### D8 — Convention Adherence

Config accessed via `project_dir()`. No direct `os.environ`. Naming follows conventions. `import numpy as np` is deferred inside methods — consistent with project pattern.


---

### File 7 — `webhook.py`

#### D1 — Code Quality & Correctness

**B-26 verification:** The SSRF fix is present and correct. `save()` calls `urlparse(url)`, checks `parsed.scheme not in _ALLOWED_SCHEMES` (frozenset `{"http", "https"}`), and checks `not parsed.netloc`. Both guards raise `ValueError` with descriptive messages. `file://`, bare paths, and schemeless URLs are all rejected. ✅

`_config_cache` is initialised as an instance attribute inside `notify()` via `hasattr` check — this is fragile. If `notify()` is called before `save()`, `_config_cache` is set from disk. If `save()` is then called, `_config_cache` is reset to `None`. But if two threads call `notify()` concurrently before `save()`, both will call `self.load()` and set `_config_cache` — a benign race but still a TOCTOU on the cache (see G3-20).

#### D2 — Architecture & Design

Fire-and-forget with daemon threads is appropriate for webhook notifications. The in-memory cache avoids a disk read per event — good. No retry logic — documented as intentional.

#### D3 — Error Handling

`_send` catches all exceptions and logs a warning — correct never-raises contract. `load()` catches all exceptions and returns `{}` — correct. `save()` raises `ValueError` for invalid URLs — correct.

#### D4 — Performance

Each `notify()` spawns a new `threading.Thread`. For high-frequency events this creates many short-lived threads. A thread pool or async approach would be more efficient (see G3-21).

#### D5 — Test Coverage Gaps

Concurrent `notify()` + `save()` race on `_config_cache` is untested. `notify()` with an empty `events` list (subscribe-all) is untested. `_send` with a non-2xx response is untested.

#### D6 — Security

SSRF prevention via scheme + netloc check is present (B-26 confirmed). No credential exposure. The webhook URL is stored in plaintext in `webhooks.json` — acceptable for a local workspace tool but worth noting.

#### D7 — Documentation

`notify()` docstring explains the cache invalidation and daemon thread behaviour — good. The fire-and-forget trade-off is documented in the daemon thread comment — excellent.

#### D8 — Convention Adherence

Config accessed via `webhooks_path()`. No direct `os.environ`. Naming follows conventions.


---

### File 8 — `ingestion.py`

#### D1 — Code Quality & Correctness

**B-31 TOCTOU verdict — see Part 3.**

`_save_hf_audio_sample`: the `dest_path.exists()` check followed by `sf.write(str(dest_path), ...)` is a classic TOCTOU race — two concurrent workers could both see `exists() == False` and both write to the same path, with the second overwrite silently winning. The fallback path uses `uuid.uuid4().hex[:6]` which reduces but does not eliminate the collision window (see B-31 verdict below).

`IngestionJob.status` is set directly (`job.status = "failed"`) without a lock. Pydantic v2 models with `model_config = {"arbitrary_types_allowed": True}` do not enforce field immutability by default, so this is a data race between the background thread (writer) and `stream_job` / `get_job` (readers) (see G3-22).

`_register_job` eviction logic removes `len(_jobs) - _MAX_COMPLETED_JOBS` oldest completed jobs — correct. But the eviction is triggered only when `len(_jobs) > _MAX_COMPLETED_JOBS` **after** adding the new job, so the store can momentarily hold `_MAX_COMPLETED_JOBS + 1` entries — acceptable.

#### D2 — Architecture & Design

`IngestionJob` uses `PrivateAttr` for the lock — correct B-30 fix. The module-level `_jobs` dict with `_jobs_lock` is clean. `stream_job` uses polling with `time.sleep(0.1)` — functional but a condition variable would be more efficient.

#### D3 — Error Handling

`_run_url_job` and `_run_hf_job` catch top-level exceptions and set `job.status = "failed"` — correct. Individual sample failures are recorded as progress events and do not abort the job — correct. `dest_path.unlink(missing_ok=True)` for corrupted files — correct.

#### D4 — Performance

`stream_job` polls every 100ms — acceptable for a streaming API. `_run_url_job` downloads files sequentially — no parallelism within a job. For large URL lists this is slow but acceptable for a background job.

#### D5 — Test Coverage Gaps

Concurrent `_save_hf_audio_sample` calls with the same `original_path` are untested. `stream_job` with a job that fails mid-stream is untested. `_register_job` eviction with exactly `_MAX_COMPLETED_JOBS + 1` jobs is untested.

#### D6 — Security

**Path traversal check:** URL-based ingestion sanitizes filenames: `filename = f"{uuid.uuid4().hex[:8]}_{Path(raw_filename).name}"`. `Path(...).name` strips directory components — correct. The UUID prefix prevents collisions and makes the filename unpredictable. ✅

HuggingFace ingestion: `original_path` from `audio_data.get("path")` is used as `Path(original_path).stem` — `Path.stem` strips directory components, so `../../etc/passwd` becomes `passwd` — correct. ✅

`label` from `label_col` is used as a directory name (`dest_dir = self.BASE_INPUT / label`) without sanitization. A malicious dataset with `label = "../../etc"` could write outside the input directory (see G3-23).

#### D7 — Documentation

`_save_hf_audio_sample` docstring describes the expected `audio_data` dict structure — good. `stream_job` documents the polling behaviour. `IngestionJob` documents the `PrivateAttr` lock rationale.

#### D8 — Convention Adherence

Config accessed via `datasets_input_dir()`. No direct `os.environ`. Naming follows conventions.


---

### File 9 — `project_manager.py`

#### D1 — Code Quality & Correctness

`generate_dataset_card()` uses `datetime.datetime.utcnow().year` — `utcnow()` is deprecated in Python 3.12+ and returns a naive datetime. Should use `datetime.datetime.now(datetime.timezone.utc).year` (see G3-24).

`validate_annotations()` compares annotation keys (which are `sample_path` strings stored in `annotations.jsonl`) against WAV file paths relative to the project dir. The WAV paths use `str(wav.relative_to(d))` which produces OS-specific separators. On Windows this would produce backslash paths while annotations stored on Linux would use forward slashes — a cross-platform mismatch. Low risk on Linux-only deployments but worth noting (see G3-25).

`list_samples()` loads all WAV files into memory before paginating — O(N) memory for large datasets (see G3-26).

`_build_histogram()` double-counts values exactly equal to a bin boundary: a value `v` where `lo <= v < hi` for bin `i` and `lo <= v <= hi` for bin `i+1` (last bin) will be counted in both if `v == hi` of a non-last bin. Actually the last-bin recount replaces the count, so values in the last bin are counted correctly. Non-last bins use `<` on the right edge — correct. No double-counting.

#### D2 — Architecture & Design

`ProjectManager` is a large class (~1000 lines) covering project lifecycle, taxonomy, contract, spec, annotations, curation, versions, snapshots, dataset ops, stats, and export. This is a God Object — violates SRP (see G3-27). The `_wav_info` / `_wav_duration_s` / `_wav_sample_rate` / `_estimate_snr` / `_build_histogram` methods duplicate functionality already in `QualityChecker` and `quality_checker.py`.

#### D3 — Error Handling

`_read_json` returns `default` on missing file but raises `json.JSONDecodeError` on corrupt JSON — callers that pass `default={}` will get an unhandled exception on corrupt files (see G3-28). `restore_version` and `restore_snapshot` use the tmp+atomic-move pattern — correct B-33 fix.

#### D4 — Performance

`get_stats()` calls `_wav_info()` (opens WAV) and `_estimate_snr()` (opens WAV again and reads all frames) for every file — two file opens per sample. `_estimate_snr` opens the file a third time inside `_wav_info` is called separately. Actually `get_stats` calls `self._wav_info(wav)` once and `self._estimate_snr(wav, sr)` once — two opens per file. Acceptable but could be merged into one open (see G3-29).

`list_samples()` calls `_wav_duration_s()` and `_wav_sample_rate()` for every WAV file on every call — O(N) file opens per page request (see G3-26).

#### D5 — Test Coverage Gaps

`generate_dataset_card()` with no spec, no labels, no sample rates is untested. `import_annotations()` with CSV missing required columns is untested. `deduplicate()` with `mode="remove"` on a read-only filesystem is untested.

#### D6 — Security

`set_spec()` writes arbitrary markdown to `spec.md` — no sanitization needed for a local file. `name` parameter in all methods is used as a directory name via `self._project_dir(name)` which calls `self.BASE / name`. A `name` containing `..` or `/` could escape the BASE directory (see G3-30).

#### D7 — Documentation

`_read_json` does not document that it raises on corrupt JSON. `get_stats` does not document the two-file-open-per-sample behaviour. `generate_dataset_card` does not document the deprecated `utcnow()` usage.

#### D8 — Convention Adherence

Config accessed via `project_dir()`. No direct `os.environ`. `datetime.datetime.utcnow()` violates the project's UTC-aware timestamp convention established in `_now()` (see G3-24).


---

### File 10 — `runtime_backend.py`

#### D1 — Code Quality & Correctness

`get_backend()` checks `_BACKEND_REGISTRY` outside the lock, then acquires `_BACKEND_INSTANCES_LOCK` for the instance cache. The registry check is a read-only operation on a dict that is only written by `register_backend()` — a TOCTOU exists if `register_backend()` is called concurrently with `get_backend()`, but this is an extremely unlikely scenario in practice (see G3-31).

`register_backend()` writes to `_BACKEND_REGISTRY` without a lock. If called concurrently with `get_backend()`, the registry dict could be in an inconsistent state (see G3-31).

#### D2 — Architecture & Design

Clean ABC + concrete implementation pattern. The singleton cache is appropriate for stateless backends. The `backend_id` property on the ABC with a default implementation is a good design. `LocalPythonBackend.execute()` is a thin delegation to `run_pipeline_ir` — correct.

#### D3 — Error Handling

`get_backend()` raises `KeyError` with a helpful message listing available backends — good. `register_backend()` raises `TypeError` for non-subclass — good.

#### D4 — Performance

No issues found. Singleton cache avoids repeated instantiation.

#### D5 — Test Coverage Gaps

`register_backend()` with a duplicate `backend_id` (overwrite) is untested. `get_backend()` after `register_backend()` invalidates the cache is untested.

#### D6 — Security

No issues found.

#### D7 — Documentation

Module docstring and class docstrings are thorough. `execute()` parameter list is fully documented. No issues.

#### D8 — Convention Adherence

No direct `os.environ`. Naming follows conventions. `__import__("threading").Lock()` for `_BACKEND_INSTANCES_LOCK` is an unusual pattern — should be a top-level `import threading` (see G3-32).

---

### File 11 — `registry_runtime.py`

#### D1 — Code Quality & Correctness

No logic — single function returning the singleton. No issues found.

#### D2 — Architecture & Design

Correct thin wrapper. The comment explaining that `AutoDiscovery` populates the registry on import is accurate and helpful.

#### D3 — Error Handling

No error handling needed — if `app.core.nodes` fails to import, the ImportError propagates naturally.

#### D4 — Performance

No issues found.

#### D5 — Test Coverage Gaps

`get_registry()` returning a populated registry (post-AutoDiscovery) is not tested in isolation.

#### D6 — Security

No issues found.

#### D7 — Documentation

Module docstring is clear. `get_registry()` docstring is adequate.

#### D8 — Convention Adherence

No direct `os.environ`. Naming follows conventions.


---

## Part 3 — Open Item Verdicts

### B-31 — TOCTOU race in `_save_hf_audio_sample` (`ingestion.py`)

**Verdict: DEFER**

**Evidence:**

```python
# ingestion.py lines ~330-340
dest_path = dest_dir / filename
if dest_path.exists():                                          # ← check
    dest_path = dest_dir / f"sample_{index:06d}_{uuid.uuid4().hex[:6]}.wav"

audio_array = np.asarray(array, dtype=np.float32)
sf.write(str(dest_path), audio_array, sampling_rate)           # ← use
```

The `exists()` → `sf.write()` gap is a TOCTOU race. Two concurrent HF job workers processing samples with the same `original_path` stem could both observe `exists() == False` and both write to `dest_path`, with the second write silently overwriting the first.

**Why DEFER, not Fix Now:** The current architecture runs one HF job per `start_hf_job()` call in a single background thread. Concurrent writes to the same `dest_dir` only occur if two separate jobs are started with the same `label` and the same `original_path` stem — an unlikely but possible scenario. The UUID fallback path (`sample_{index:06d}_{uuid.uuid4().hex[:6]}.wav`) reduces the collision window but does not eliminate it.

**Recommended fix (for next sprint):** Use `O_CREAT | O_EXCL` semantics via a temp-file-then-rename pattern:

```python
import tempfile, os
tmp_fd, tmp_path = tempfile.mkstemp(dir=dest_dir, suffix=".wav")
os.close(tmp_fd)
sf.write(tmp_path, audio_array, sampling_rate)
final_path = dest_dir / filename
os.replace(tmp_path, str(final_path))   # atomic on POSIX
```

This is atomic on POSIX and eliminates the race entirely.

---

### B-26 — SSRF fix in `webhook.py`

**Verdict: CONFIRMED PRESENT AND CORRECT ✅**

**Evidence:**

```python
# webhook.py lines 18-19
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# webhook.py save() method
parsed = urlparse(url)
if parsed.scheme not in _ALLOWED_SCHEMES:
    raise ValueError(
        f"Webhook URL must use http or https scheme, "
        f"got {parsed.scheme!r}. URL: {url!r}"
    )
if not parsed.netloc:
    raise ValueError(
        f"Webhook URL must have a valid host. URL: {url!r}"
    )
```

Both the scheme allowlist and the netloc (host) presence check are in place. `file://`, `ftp://`, bare paths, and schemeless URLs are all rejected. The guard is applied at `save()` time, so stored URLs are always valid. No host allowlist (only scheme + netloc presence) — this is the documented scope of B-26.

---

### B-01 — `_artifacts` thread-safety in `run_manager.py`

**Verdict: FIXED ✅**

**Evidence:**

```python
# run_manager.py __init__
self._artifacts: list[ArtifactRecord] = []
self._artifacts_lock = threading.Lock()  # guards concurrent appends

# register_artifact()
with self._artifacts_lock:
    self._artifacts.append(record)
return record

# artifacts property
@property
def artifacts(self) -> list[ArtifactRecord]:
    with self._artifacts_lock:
        return list(self._artifacts)
```

Both the `append` in `register_artifact()` and the read in the `artifacts` property are protected by `_artifacts_lock`. The property returns a copy (`list(self._artifacts)`) so callers cannot mutate the internal list. Thread-safe. ✅

---

### B-13 — `record()` thread-safety in `provenance.py`

**Verdict: FIXED ✅**

**Evidence:**

```python
# provenance.py record()
with self._lock:
    # Write {artifact_id}.json
    record_path.write_text(...)
    # Read-modify-write by_run/{run_id}.json
    by_run_path.write_text(json.dumps(existing, indent=2), ...)
    # Read-modify-write by_graph_hash/{hash[:16]}.json
    by_hash_path.write_text(json.dumps(hash_ids, indent=2), ...)
```

The entire read-modify-write cycle for all three files is inside `self._lock`. Concurrent calls on the same artifact will serialize correctly. ✅


---

## Part 4 — Findings Catalogue

### [G3-01] `update_resume_state` is not atomic under concurrent node completion
**File:** `app/core/run_manager.py`  
**Severity:** 🟠 High  
**Dimension:** D1 — Code Quality & Correctness  
**Description:** `update_resume_state()` reads `resume_state.json`, appends a `node_id`, then writes it back — all without a lock. In parallel wave execution, two nodes completing simultaneously will both read the same state, each append their own `node_id`, and the second write will overwrite the first, silently losing one completed node from the checkpoint.  
**Evidence:** `run_manager.py` — `update_resume_state()` method; no lock around the read-modify-write cycle.  
**Proposed Fix:** Protect the read-modify-write with `self._meta_lock` (already exists), or use a dedicated `_resume_lock`. Alternatively, append to a separate per-node file and merge on read.

---

### [G3-02] `find_latest_checkpoint` mtime fallback sorts incorrectly against ISO timestamps
**File:** `app/core/run_manager.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1 — Code Quality & Correctness  
**Description:** When `created_at` is missing from `meta.json`, the fallback is `str(mtime)` — a float like `"1720000000.123"`. This string sorts lexicographically before any ISO 8601 string (which starts with `"20..."`), so a run with a missing `created_at` will always be ranked as the oldest, even if it is the newest. The wrong checkpoint will be selected.  
**Evidence:** `run_manager.py` `find_latest_checkpoint()` — `created_at = str(mtime)` fallback; `candidates.sort(key=lambda x: x[0], reverse=True)`.  
**Proposed Fix:** Convert mtime to an ISO string: `created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()`.

---

### [G3-03] `find_latest_checkpoint` imports a private function from `pipeline.py`
**File:** `app/core/run_manager.py`  
**Severity:** 🟡 Medium  
**Dimension:** D2 — Architecture & Design  
**Description:** `from app.core.pipeline import _load_checkpoint_outputs` — importing a private (underscore-prefixed) function creates a fragile coupling. Any refactor of `pipeline.py` that renames or removes `_load_checkpoint_outputs` will silently break checkpoint resumption.  
**Evidence:** `run_manager.py` `find_latest_checkpoint()` — `from app.core.pipeline import _load_checkpoint_outputs`.  
**Proposed Fix:** Promote `_load_checkpoint_outputs` to a public function in `pipeline.py`, or move it to a shared `checkpoint.py` utility module.

---

### [G3-04] `update_resume_state` raises uncaught `json.JSONDecodeError` on corrupt state file
**File:** `app/core/run_manager.py`  
**Severity:** 🟠 High  
**Dimension:** D3 — Error Handling  
**Description:** If `resume_state.json` exists but is corrupt (e.g. truncated by a previous crash), `json.load(f)` raises `json.JSONDecodeError` which propagates uncaught, crashing the pipeline executor thread.  
**Evidence:** `run_manager.py` `update_resume_state()` — `state = json.load(f)` with no try/except.  
**Proposed Fix:**
```python
try:
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
except Exception:
    logger.warning("resume_state.json corrupt for run %s — skipping update", self.run_id)
    return
```

---

### [G3-05] `find_latest_checkpoint` path constructed from unsanitized `os.listdir` entry
**File:** `app/core/run_manager.py`  
**Severity:** 🟠 High  
**Dimension:** D6 — Security  
**Description:** `run_dir_name` comes from `os.listdir(runs_dir_path)`. A symlink or directory named `../../etc` in the runs directory would cause `checkpoint_dir` to point outside the workspace. While creating such a symlink requires filesystem access, it is a defence-in-depth concern.  
**Evidence:** `run_manager.py` `find_latest_checkpoint()` — `checkpoint_dir = os.path.join(runs_dir_path, run_dir_name, "checkpoints", ...)`.  
**Proposed Fix:** Validate that the resolved path is under `runs_dir_path`:
```python
resolved = Path(os.path.join(runs_dir_path, run_dir_name)).resolve()
if not str(resolved).startswith(str(Path(runs_dir_path).resolve())):
    continue
```


---

### [G3-06] `summary()` emits two log entries for the same event
**File:** `app/core/logger.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1 — Code Quality & Correctness  
**Description:** `summary()` calls `self.info(...)` (which appends a plain-text entry via `_emit`) and then `self._emit_structured(...)` (which appends a structured entry). Both go into `self.logs` and onto `self.queue`. Consumers that process all log entries will see a duplicate completion event.  
**Evidence:** `logger.py` `summary()` — `self.info(f"Pipeline completed in {total:.3f}s")` followed by `self._emit_structured({"type": "pipeline_summary", ...})`.  
**Proposed Fix:** Remove the `self.info(...)` call from `summary()` and include the human-readable message inside the structured event, or emit only the structured event and let consumers format it.

---

### [G3-07] `deque` iteration in `save_logs` is not atomic with concurrent appends
**File:** `app/core/logger.py`  
**Severity:** 🟡 Medium  
**Dimension:** D2 — Architecture & Design  
**Description:** `run_manager.save_logs(logs)` calls `list(logs)` on the `deque`. While `deque.append` is GIL-atomic, `list(deque)` is not atomic with concurrent appends — the resulting list may contain a partially-updated view. In practice the GIL makes this safe on CPython, but it is not guaranteed on other Python implementations.  
**Evidence:** `run_manager.py` `save_logs()` — `json.dump(list(logs), f, ...)`.  
**Proposed Fix:** Add a snapshot method to `PipelineLogger` that returns a copy under a lock, similar to `IngestionJob.read_progress()`.

---

### [G3-08] `queue.put()` in `_emit` / `_emit_structured` can block indefinitely
**File:** `app/core/logger.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3 — Error Handling  
**Description:** If `self.queue` is a bounded `Queue` and the consumer is slow, `self.queue.put(entry)` will block the pipeline executor thread indefinitely. No timeout or `put_nowait` guard is present.  
**Evidence:** `logger.py` `_emit()` — `self.queue.put(entry)`; `_emit_structured()` — `self.queue.put(entry)`.  
**Proposed Fix:** Use `self.queue.put_nowait(entry)` with a `queue.Full` catch and a warning log, or use `self.queue.put(entry, timeout=1.0)`.

---

### [G3-09] Deduplicated artifacts are not added to the `by_run` secondary index
**File:** `app/core/artifact_store.py`  
**Severity:** 🟠 High  
**Dimension:** D1 — Code Quality & Correctness  
**Description:** When `register()` finds an existing artifact by content hash, it returns a copy stamped with the current `run_id` but does **not** call `_append_by_run(run_id, artifact_id)`. Consequently, `list(run_id=X)` via the fast path will not return deduplicated artifacts for run X, making the run's artifact list incomplete.  
**Evidence:** `artifact_store.py` `register()` — the deduplication early-return path (lines ~200-215) returns without calling `_append_by_run`.  
**Proposed Fix:** Call `self._append_by_run(run_id, existing.artifact_id)` before returning the deduplicated record.

---

### [G3-10] `get_versions()` performs an O(N) full directory scan
**File:** `app/core/artifact_store.py`  
**Severity:** 🟡 Medium  
**Dimension:** D4 — Performance  
**Description:** `get_versions(artifact_name)` calls `self.list()` with no filters, triggering the full directory scan slow path. For stores with thousands of artifacts this is O(N) disk reads.  
**Evidence:** `artifact_store.py` `get_versions()` — `return [r for r in self.list() if r.name == artifact_name]`.  
**Proposed Fix:** Add a `by_name/` secondary index (similar to `by_run/`) populated in `register()`, or accept the current O(N) behaviour and document it as a known limitation.


---

### [G3-11] `ArtifactStore._lock` serializes all concurrent artifact registrations including disk I/O
**File:** `app/core/artifact_store.py`  
**Severity:** 🟡 Medium  
**Dimension:** D2 — Architecture & Design  
**Description:** The single `self._lock` is held for the entire `register()` critical section, including `_serialize_data()` which writes WAV files or JSON to disk. In parallel wave execution with many nodes, all artifact registrations are serialized, creating a throughput bottleneck.  
**Evidence:** `artifact_store.py` `register()` — `with self._lock:` wraps `_serialize_data()`, `_save_index()`, and `_append_by_run()`.  
**Proposed Fix:** Move `_serialize_data()` outside the lock (it writes to a unique `artifact_id` directory), and only hold the lock for the index read-modify-write. Requires generating `artifact_id` before acquiring the lock.

---

### [G3-12] Partial `artifact_dir` not cleaned up on `ArtifactSerializationError`
**File:** `app/core/artifact_store.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3 — Error Handling  
**Description:** If `_serialize_data()` raises `ArtifactSerializationError` after creating `artifact_dir` but before writing `record.json`, the orphaned directory remains on disk. The index is not updated, so the artifact is not registered, but the directory wastes space and may confuse future scans.  
**Evidence:** `artifact_store.py` `register()` — `self._serialize_data(artifact_type, data, data_dir)` can raise; no cleanup of `artifact_dir` in the except path.  
**Proposed Fix:**
```python
try:
    self._serialize_data(artifact_type, data, data_dir)
except ArtifactSerializationError:
    shutil.rmtree(str(artifact_dir), ignore_errors=True)
    raise
```

---

### [G3-13] `find_reproducible` assigns `None` to a `list[str]` variable on index read failure
**File:** `app/core/provenance.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1 — Code Quality & Correctness  
**Description:** When reading `by_hash_path` raises an exception, `artifact_ids = None` is assigned with a `# type: ignore` comment. The `else` branch (which processes the list) is skipped, and execution falls through to the slow-path scan — the intended behaviour. However, the `None` assignment is confusing and the type annotation is wrong.  
**Evidence:** `provenance.py` `find_reproducible()` — `artifact_ids = None  # type: ignore[assignment]` in the except block.  
**Proposed Fix:** Use a sentinel flag instead:
```python
use_fast_path = True
try:
    artifact_ids = json.loads(...)
except Exception:
    use_fast_path = False
if use_fast_path:
    ...
    return records
# slow path
```

---

### [G3-14] `record()` silently overwrites existing provenance for the same `artifact_id`
**File:** `app/core/provenance.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3 — Error Handling  
**Description:** If `record()` is called twice for the same `artifact_id` (e.g. a deduplicated artifact registered in two runs), the second call overwrites the first `{artifact_id}.json` with only a warning log. The original provenance (first run's context) is permanently lost.  
**Evidence:** `provenance.py` `record()` — `if record_path.exists(): logger.warning(...)` then `record_path.write_text(...)`.  
**Proposed Fix:** Either raise an error on duplicate (strict mode) or append to a list of provenance records per artifact (multi-run tracking). At minimum, document this behaviour in the docstring.

---

### [G3-15] `by_run_path.write_text()` in `record()` is not atomic
**File:** `app/core/provenance.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3 — Error Handling  
**Description:** `by_run_path.write_text(json.dumps(existing, indent=2), ...)` writes directly to the target file. A crash or `KeyboardInterrupt` mid-write will corrupt the `by_run` index. The same issue applies to `by_hash_path.write_text(...)`.  
**Evidence:** `provenance.py` `record()` — direct `write_text` calls for both index files.  
**Proposed Fix:** Use the tmp+replace pattern (already used in `ArtifactStore._save_index`):
```python
tmp = by_run_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
tmp.replace(by_run_path)
```


---

### [G3-16] `_check_snr` docstring claims "non-silent frames" but uses whole-file mean power
**File:** `app/core/quality_checker.py`  
**Severity:** 🟡 Medium  
**Dimension:** D7 — Documentation  
**Description:** The docstring states `signal_power = mean of squared non-silent frames` but the implementation computes `float(np.mean(audio_data ** 2))` — the mean power of the entire file including silence. This misleads maintainers about the SNR algorithm.  
**Evidence:** `quality_checker.py` `_check_snr()` — docstring vs `signal_power = float(np.mean(audio_data ** 2))`.  
**Proposed Fix:** Update the docstring to accurately describe the implementation: "signal_power = mean squared amplitude of the entire file (not VAD-filtered)."

---

### [G3-17] Duplicate detection silently degrades when `librosa` is unavailable
**File:** `app/core/quality_checker.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1 — Code Quality & Correctness  
**Description:** When `librosa` is unavailable, `_check_duplicate` skips resampling and hashes the original-SR mono signal. Two files with identical content but different sample rates will not be detected as duplicates. The warning log is present but the quality report does not indicate that duplicate detection was degraded.  
**Evidence:** `quality_checker.py` `_check_duplicate()` — `except Exception: logger.warning("resampling skipped...")`.  
**Proposed Fix:** Add a finding to the results when resampling is skipped: `{"check_name": "duplicates", "severity": "warning", "detail": "Resampling unavailable — cross-SR duplicate detection disabled"}`.

---

### [G3-18] `_persist()` return value assigned but never used in `run()`
**File:** `app/core/quality_checker.py`  
**Severity:** 🔵 Low  
**Dimension:** D1 — Code Quality & Correctness  
**Description:** `run()` assigns `report_saved = self._persist(project_dir, findings)` but `_persist` returns `None`. The variable `report_saved` is never used. This is dead code that misleads readers into thinking the return value matters.  
**Evidence:** `quality_checker.py` `run()` — `report_saved = self._persist(project_dir, findings)`.  
**Proposed Fix:** Change to `self._persist(project_dir, findings)` (no assignment).

---

### [G3-19] `run()` loads every WAV file fully into memory — O(N × file_size) peak memory
**File:** `app/core/quality_checker.py`  
**Severity:** 🟡 Medium  
**Dimension:** D4 — Performance  
**Description:** `_load_audio()` loads the full audio array for every WAV file. For a dataset with 10,000 × 5-second 16kHz files, peak memory is ~3.2 GB. There is no streaming or batching.  
**Evidence:** `quality_checker.py` `run()` — `audio_data, sr = self._load_audio(wav_path)` inside the per-file loop.  
**Proposed Fix:** Process files in batches and release memory between batches, or use `soundfile` streaming reads for checks that don't need the full array (e.g. clipping can be checked on chunks).

---

### [G3-20] `_config_cache` in `WebhookService` has a benign TOCTOU under concurrent `notify()` calls
**File:** `app/core/webhook.py`  
**Severity:** 🔵 Low  
**Dimension:** D1 — Code Quality & Correctness  
**Description:** Two threads calling `notify()` simultaneously before `save()` will both find `_config_cache` absent and both call `self.load()`, resulting in two disk reads and two assignments to `_config_cache`. The final value is correct (both reads return the same config), but the double-read is wasteful and the `hasattr` pattern is fragile.  
**Evidence:** `webhook.py` `notify()` — `if not hasattr(self, "_config_cache") or self._config_cache is None: self._config_cache = self.load()`.  
**Proposed Fix:** Initialize `_config_cache: dict | None = None` as a class-level attribute in `__init__`, and use a lock for the lazy-load pattern.

---

### [G3-21] `notify()` spawns a new thread per event — no thread pool
**File:** `app/core/webhook.py`  
**Severity:** 🟡 Medium  
**Dimension:** D4 — Performance  
**Description:** Each call to `notify()` creates a new `threading.Thread`. For pipelines that emit many events (e.g. one per node), this creates many short-lived threads. Thread creation has non-trivial overhead and the OS has a thread limit.  
**Evidence:** `webhook.py` `notify()` — `thread = threading.Thread(target=self._send, ...)`.  
**Proposed Fix:** Use a `concurrent.futures.ThreadPoolExecutor` with a small pool (e.g. 2 workers) to bound thread count and reuse threads.


---

### [G3-22] `IngestionJob.status` written without a lock — data race with `stream_job`
**File:** `app/core/ingestion.py`  
**Severity:** 🟠 High  
**Dimension:** D6 — Security / D1 — Code Quality & Correctness  
**Description:** The background worker sets `job.status = "failed"` or `job.status = "completed"` directly. `stream_job()` reads `job.status` in the polling loop without a lock. On CPython the GIL makes simple attribute assignment atomic, but this is an implementation detail, not a language guarantee. More critically, `stream_job` checks `job.status != "running"` and then drains remaining events — if the status write and the final `append_progress` are reordered by the CPU or compiler, `stream_job` may exit before the final events are drained.  
**Evidence:** `ingestion.py` `_run_url_job()` — `job.status = "completed"` after `job.append_progress(...)`.  
**Proposed Fix:** Add a `set_status(status)` method to `IngestionJob` that acquires `_lock` before writing, and use it in all workers.

---

### [G3-23] `label` from HuggingFace dataset used as directory name without sanitization
**File:** `app/core/ingestion.py`  
**Severity:** 🔴 Critical  
**Dimension:** D6 — Security  
**Description:** `label = str(sample[label_col])` is used directly as `dest_dir = self.BASE_INPUT / label`. A malicious HuggingFace dataset with a label value of `"../../etc"` or `"../../../tmp/evil"` would cause audio files to be written outside the `datasets/input/` directory — a path traversal attack.  
**Evidence:** `ingestion.py` `_run_hf_job()` — `label = str(sample[label_col])` then `dest_dir = self.BASE_INPUT / label`.  
**Proposed Fix:** Sanitize the label before using it as a path component:
```python
import re
label = re.sub(r'[^\w\-]', '_', str(sample[label_col]))[:64]
dest_dir = self.BASE_INPUT / label
# Verify the resolved path is still under BASE_INPUT
if not str(dest_dir.resolve()).startswith(str(self.BASE_INPUT.resolve())):
    raise ValueError(f"Label '{label}' would escape the input directory")
```

---

### [G3-24] `generate_dataset_card()` uses deprecated `datetime.datetime.utcnow()`
**File:** `app/core/project_manager.py`  
**Severity:** 🟡 Medium  
**Dimension:** D8 — Convention Adherence  
**Description:** `datetime.datetime.utcnow().year` uses the deprecated `utcnow()` which returns a naive datetime. Python 3.12 emits a `DeprecationWarning`. The rest of the codebase uses `datetime.datetime.now(datetime.timezone.utc)` (see `_now()` in the same file).  
**Evidence:** `project_manager.py` `generate_dataset_card()` — `year = {{{datetime.datetime.utcnow().year}}}`.  
**Proposed Fix:** `datetime.datetime.now(datetime.timezone.utc).year`.

---

### [G3-25] `validate_annotations()` path comparison may fail on Windows due to separator mismatch
**File:** `app/core/project_manager.py`  
**Severity:** 🔵 Low  
**Dimension:** D1 — Code Quality & Correctness  
**Description:** WAV paths are stored as `str(wav.relative_to(d))` which uses OS-native separators. Annotation `sample_path` values stored on Linux use `/`. On Windows, the comparison `all_wav - annotated` would find no matches, reporting all samples as unannotated.  
**Evidence:** `project_manager.py` `validate_annotations()` — `rel = str(wav.relative_to(d))` vs annotation keys from `annotations.jsonl`.  
**Proposed Fix:** Normalize separators: `rel = wav.relative_to(d).as_posix()` and store/compare annotation paths as POSIX strings.

---

### [G3-26] `list_samples()` opens every WAV file for duration/SR on every call
**File:** `app/core/project_manager.py`  
**Severity:** 🟠 High  
**Dimension:** D4 — Performance  
**Description:** `list_samples()` calls `_wav_duration_s(wav)` and `_wav_sample_rate(wav)` for every WAV file in the version directory, even for files that will be filtered out or are outside the requested page. For a version with 10,000 files, a page-1 request opens 10,000 WAV files.  
**Evidence:** `project_manager.py` `list_samples()` — `"duration_s": self._wav_duration_s(wav)` inside the per-file loop before pagination.  
**Proposed Fix:** Apply pagination before reading WAV metadata, or cache metadata in a sidecar JSON file (e.g. `metadata_cache.json`) that is updated when files are added.

---

### [G3-27] `ProjectManager` is a God Object (~1000 lines, 12+ responsibilities)
**File:** `app/core/project_manager.py`  
**Severity:** 🟡 Medium  
**Dimension:** D2 — Architecture & Design  
**Description:** `ProjectManager` handles project lifecycle, taxonomy, contract, spec, annotations, curation, versions, snapshots, dataset stats, sample listing, deduplication, quality export, and dataset card generation. This violates SRP and makes the class difficult to test and extend. Several methods (`_estimate_snr`, `_build_histogram`, `_wav_info`) duplicate logic from `QualityChecker`.  
**Evidence:** `project_manager.py` — class spans ~1000 lines with 12+ distinct responsibility groups.  
**Proposed Fix:** Extract into focused services: `AnnotationService`, `VersionService`, `DatasetStatsService`. Share `_wav_info` and `_estimate_snr` via a utility module.

---

### [G3-28] `_read_json` raises `json.JSONDecodeError` on corrupt files — callers not guarded
**File:** `app/core/project_manager.py`  
**Severity:** 🟡 Medium  
**Dimension:** D3 — Error Handling  
**Description:** `_read_json` returns `default` only for missing files. A corrupt `project.json`, `contract.json`, or `taxonomy.json` will raise `json.JSONDecodeError` which propagates uncaught through all callers (e.g. `list_all()`, `get_contract()`, `get_taxonomy()`).  
**Evidence:** `project_manager.py` `_read_json()` — `return json.load(f)` with no except for `JSONDecodeError`.  
**Proposed Fix:**
```python
try:
    return json.load(f)
except json.JSONDecodeError:
    logger.warning("Corrupt JSON at %s — returning default", path)
    return default
```

---

### [G3-29] `get_stats()` opens each WAV file twice (metadata + SNR)
**File:** `app/core/project_manager.py`  
**Severity:** 🟡 Medium  
**Dimension:** D4 — Performance  
**Description:** `get_stats()` calls `self._wav_info(wav)` (opens WAV, reads header) and then `self._estimate_snr(wav, sr)` (opens WAV again, reads all frames). Two file opens per sample.  
**Evidence:** `project_manager.py` `get_stats()` — `dur, sr = self._wav_info(wav)` then `snr = self._estimate_snr(wav, sr)`.  
**Proposed Fix:** Merge into a single open that reads both header and frames in one pass.

---

### [G3-30] Project `name` parameter used as directory name without path traversal check
**File:** `app/core/project_manager.py`  
**Severity:** 🟠 High  
**Dimension:** D6 — Security  
**Description:** `self._project_dir(name)` returns `self.BASE / name`. If `name` contains `..` or `/`, the resulting path escapes `BASE`. For example, `name = "../runs"` would point to the runs directory. All project operations (read, write, delete) would operate on the wrong directory.  
**Evidence:** `project_manager.py` `_project_dir()` — `return self.BASE / name`.  
**Proposed Fix:** Validate `name` at the entry points (`create`, `rename`, `delete`, etc.):
```python
import re
_SAFE_NAME_RE = re.compile(r'^[\w\-]{1,128}$')
if not _SAFE_NAME_RE.match(name):
    raise ValueError(f"Invalid project name: {name!r}")
```


---

### [G3-31] `_BACKEND_REGISTRY` written without a lock in `register_backend()`
**File:** `app/core/runtime_backend.py`  
**Severity:** 🟡 Medium  
**Dimension:** D1 — Code Quality & Correctness  
**Description:** `register_backend()` writes to `_BACKEND_REGISTRY` (a plain dict) without a lock. `get_backend()` reads `_BACKEND_REGISTRY` outside the lock. Concurrent calls to `register_backend()` and `get_backend()` could observe a partially-updated dict on non-CPython implementations.  
**Evidence:** `runtime_backend.py` `register_backend()` — `_BACKEND_REGISTRY[backend_id] = backend_class` with no lock; `get_backend()` — `if backend_id not in _BACKEND_REGISTRY` with no lock.  
**Proposed Fix:** Protect `_BACKEND_REGISTRY` reads and writes with `_BACKEND_INSTANCES_LOCK` (already exists), or add a dedicated `_BACKEND_REGISTRY_LOCK`.

---

### [G3-32] `_BACKEND_INSTANCES_LOCK` uses `__import__("threading").Lock()` — non-idiomatic
**File:** `app/core/runtime_backend.py`  
**Severity:** 🔵 Low  
**Dimension:** D8 — Convention Adherence  
**Description:** `_BACKEND_INSTANCES_LOCK = __import__("threading").Lock()` is an unusual pattern used to avoid a top-level `import threading` statement. The project uses `import threading` at the top of other files — this should be consistent.  
**Evidence:** `runtime_backend.py` — `_BACKEND_INSTANCES_LOCK = __import__("threading").Lock()`.  
**Proposed Fix:** Add `import threading` at the top of the file and use `threading.Lock()`.


---

## Part 5 — Summary Table

| ID | File | Severity | Dimension | Short Title |
|----|------|----------|-----------|-------------|
| G3-01 | `run_manager.py` | 🟠 High | D1 | `update_resume_state` not atomic under concurrent node completion |
| G3-02 | `run_manager.py` | 🟡 Medium | D1 | mtime fallback sorts incorrectly against ISO timestamps |
| G3-03 | `run_manager.py` | 🟡 Medium | D2 | Imports private `_load_checkpoint_outputs` from `pipeline.py` |
| G3-04 | `run_manager.py` | 🟠 High | D3 | `update_resume_state` raises uncaught on corrupt state file |
| G3-05 | `run_manager.py` | 🟠 High | D6 | Path from unsanitized `os.listdir` entry in checkpoint lookup |
| G3-06 | `logger.py` | 🟡 Medium | D1 | `summary()` emits two log entries for the same event |
| G3-07 | `logger.py` | 🟡 Medium | D2 | `deque` iteration in `save_logs` not atomic with concurrent appends |
| G3-08 | `logger.py` | 🟡 Medium | D3 | `queue.put()` can block pipeline thread indefinitely |
| G3-09 | `artifact_store.py` | 🟠 High | D1 | Deduplicated artifacts missing from `by_run` secondary index |
| G3-10 | `artifact_store.py` | 🟡 Medium | D4 | `get_versions()` O(N) full directory scan |
| G3-11 | `artifact_store.py` | 🟡 Medium | D2 | Single lock serializes all artifact registrations including disk I/O |
| G3-12 | `artifact_store.py` | 🟡 Medium | D3 | Partial `artifact_dir` not cleaned up on serialization failure |
| G3-13 | `provenance.py` | 🟡 Medium | D1 | `None` assigned to `list[str]` variable on index read failure |
| G3-14 | `provenance.py` | 🟡 Medium | D3 | `record()` silently overwrites existing provenance |
| G3-15 | `provenance.py` | 🟡 Medium | D3 | `by_run_path.write_text()` not atomic — crash corrupts index |
| G3-16 | `quality_checker.py` | 🟡 Medium | D7 | `_check_snr` docstring claims "non-silent frames" but uses whole-file mean |
| G3-17 | `quality_checker.py` | 🟡 Medium | D1 | Duplicate detection silently degrades without `librosa` |
| G3-18 | `quality_checker.py` | 🔵 Low | D1 | `_persist()` return value assigned but never used |
| G3-19 | `quality_checker.py` | 🟡 Medium | D4 | O(N × file_size) peak memory — no batching |
| G3-20 | `webhook.py` | 🔵 Low | D1 | `_config_cache` benign TOCTOU under concurrent `notify()` |
| G3-21 | `webhook.py` | 🟡 Medium | D4 | New thread per event — no thread pool |
| G3-22 | `ingestion.py` | 🟠 High | D1 | `IngestionJob.status` written without lock — data race |
| G3-23 | `ingestion.py` | 🔴 Critical | D6 | `label` from HuggingFace dataset used as directory name — path traversal |
| G3-24 | `project_manager.py` | 🟡 Medium | D8 | `datetime.utcnow()` deprecated — violates UTC-aware convention |
| G3-25 | `project_manager.py` | 🔵 Low | D1 | Path separator mismatch in `validate_annotations()` on Windows |
| G3-26 | `project_manager.py` | 🟠 High | D4 | `list_samples()` opens every WAV file on every call before pagination |
| G3-27 | `project_manager.py` | 🟡 Medium | D2 | `ProjectManager` is a God Object (~1000 lines, 12+ responsibilities) |
| G3-28 | `project_manager.py` | 🟡 Medium | D3 | `_read_json` raises on corrupt JSON — callers not guarded |
| G3-29 | `project_manager.py` | 🟡 Medium | D4 | `get_stats()` opens each WAV file twice |
| G3-30 | `project_manager.py` | 🟠 High | D6 | Project `name` used as directory name without path traversal check |
| G3-31 | `runtime_backend.py` | 🟡 Medium | D1 | `_BACKEND_REGISTRY` written without lock |
| G3-32 | `runtime_backend.py` | 🔵 Low | D8 | `__import__("threading")` pattern — non-idiomatic |

---

### Totals by Severity

| Severity | Count |
|----------|-------|
| 🔴 Critical | 1 |
| 🟠 High | 8 |
| 🟡 Medium | 18 |
| 🔵 Low | 5 |
| **Total** | **32** |

---

### Open Item Summary

| Item | File | Verdict |
|------|------|---------|
| B-31 TOCTOU in `_save_hf_audio_sample` | `ingestion.py` | **DEFER** — race exists but requires concurrent jobs with same label+stem; fix with tmp+replace pattern |
| B-26 SSRF allowlist | `webhook.py` | **CONFIRMED PRESENT ✅** — scheme + netloc guards in place |
| B-01 `_artifacts` thread-safety | `run_manager.py` | **CONFIRMED FIXED ✅** — `_artifacts_lock` guards both append and read |
| B-13 `record()` thread-safety | `provenance.py` | **CONFIRMED FIXED ✅** — entire read-modify-write inside `self._lock` |

---

*End of report — G3 Backend Services*
