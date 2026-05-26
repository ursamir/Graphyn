# Functional Review — PluginPackage/Common/experiment_tracker/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/experiment_tracker/nodes.py
FUNCTION:    ExperimentTrackerNode._log_mlflow
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Log experiment parameters, metrics, and artifacts to MLflow."

WHAT IT ACTUALLY DOES:
Calls `mlflow.start_run(run_name=run_id)` as a context manager. If the MLflow
tracking server is unavailable (network error, wrong URI, server down), MLflow
raises `MlflowException` or `ConnectionError` inside the `with` block. This
exception propagates out of `_log_mlflow` and out of `process()`, causing the
entire pipeline to fail.

THE BUG / RISK:
MLflow backend unavailability causes a hard pipeline failure. The group-specific
focus area explicitly calls out "handle backend unavailability." There is no
retry, no fallback to JSON, and no graceful degradation.

EVIDENCE:
```python
def _log_mlflow(self, run_id, params, metrics, artifact_paths):
    import mlflow
    if self.config.tracking_uri:
        mlflow.set_tracking_uri(self.config.tracking_uri)
    mlflow.set_experiment(self.config.experiment_name)
    with mlflow.start_run(run_name=run_id):   # raises if server unavailable
        mlflow.log_params(flat_params)
        ...
```

REPRODUCTION SCENARIO:
Set `tracking_uri="http://nonexistent-mlflow-server:5000"`. Call `process()`.
`mlflow.set_tracking_uri` succeeds (lazy), but `mlflow.start_run()` raises
`MlflowException: Could not connect to tracking server`.

IMPACT:
Pipeline crash when MLflow server is unavailable. No experiment data is saved.
The JSON fallback is not used.

FIX DIRECTION:
Wrap the MLflow call and fall back to JSON on failure:
```python
try:
    self._log_mlflow(run_id, params, metrics, artifact_paths)
except Exception as exc:
    log.warning(
        "ExperimentTrackerNode: MLflow logging failed (%s). "
        "Falling back to JSON backend.", exc
    )
    self._log_json(run_id, params, metrics, artifact_paths, env_meta)
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/experiment_tracker/nodes.py
FUNCTION:    ExperimentTrackerNode._capture_env
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Capture environment info once at setup time."

WHAT IT ACTUALLY DOES:
Calls `subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], timeout=5)`.
The `except Exception: pass` swallows all errors, which is correct for the git
hash. However, the `timeout=5` is passed to `subprocess.check_output`. If the
git command hangs for exactly 5 seconds on every call (e.g., in a network-mounted
filesystem), `setup()` blocks for 5 seconds. Since `setup()` is called once per
node instantiation, this is a one-time cost, but it can cause unexpected latency
in pipeline startup.

THE BUG / RISK:
5-second blocking delay in `setup()` on systems where `git` is slow (network
filesystem, large repo). This is a performance correctness issue, not a crash.

EVIDENCE:
```python
git_hash = subprocess.check_output(
    ["git", "rev-parse", "--short", "HEAD"],
    stderr=subprocess.DEVNULL,
    timeout=5,   # blocks for up to 5 seconds
).decode().strip()
```

REPRODUCTION SCENARIO:
Run on a system with a slow git (NFS-mounted repo). `setup()` takes 5 seconds.

IMPACT:
Pipeline startup latency. No data loss.

FIX DIRECTION:
Reduce timeout or run asynchronously:
```python
timeout=1,  # 1 second is sufficient for local git
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/experiment_tracker/nodes.py
FUNCTION:    ExperimentTrackerNode._extract
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Extract parameters, metrics, and artifact paths from any artifact object."

WHAT IT ACTUALLY DOES:
Iterates over `artifact.history` (if it exists) and adds all keys to `metrics`.
If `history` contains non-numeric values (e.g., a list of dicts, or a nested
dict from a custom training loop), these are added to `metrics` as-is. Later,
in `_log_mlflow`, the code filters `if isinstance(v, (int, float))` before
logging, so non-numeric values are silently dropped from MLflow. In `_log_json`,
`json.dump(..., default=str)` converts them to strings. This is inconsistent
behavior between backends.

THE BUG / RISK:
Non-numeric history values are silently dropped in MLflow but stringified in
JSON. A user comparing MLflow and JSON logs will see different data.

EVIDENCE:
```python
# _extract:
for k, v in history.items():
    metrics[k] = v   # any type accepted

# _log_mlflow:
for k, v in metrics.items():
    if isinstance(v, (int, float)):
        mlflow.log_metric(k, float(v))   # non-numeric silently dropped
    elif isinstance(v, list) and all(isinstance(x, (int, float)) for x in v):
        for step, val in enumerate(v):
            mlflow.log_metric(k, float(val), step=step)
```

REPRODUCTION SCENARIO:
Pass a ModelArtifact with `history={"loss": [0.5, 0.3], "config": {"lr": 0.001}}`.
MLflow logs `loss` as a metric series. `config` is silently dropped from MLflow
but appears as a string in JSON.

IMPACT:
Silent data loss in MLflow backend. Inconsistent experiment records.

FIX DIRECTION:
Log a warning when non-numeric metrics are dropped:
```python
else:
    log.debug("ExperimentTrackerNode: skipping non-numeric metric '%s' (type=%s)", k, type(v).__name__)
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/experiment_tracker/nodes.py
FUNCTION:    ExperimentTrackerNode._log_json
CATEGORY:    Resource Leak
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Write experiment record to JSON file."

WHAT IT ACTUALLY DOES:
Opens `out_path` with `open(out_path, "w")` and calls `json.dump(record, f, ...)`.
If `json.dump` raises (e.g., a non-serializable value slips through `default=str`
for a custom object that raises in `__str__`), the file handle is properly closed
by the `with` statement. This is safe. However, if `run_dir.mkdir(parents=True,
exist_ok=True)` fails (permission error), the exception propagates without a
clear error message about which directory failed.

THE BUG / RISK:
Permission error on `run_dir.mkdir` produces a generic `PermissionError` without
context about which path failed. Low severity.

EVIDENCE:
```python
run_dir = Path(self.config.output_dir) / run_id
run_dir.mkdir(parents=True, exist_ok=True)   # PermissionError if no write access
```

REPRODUCTION SCENARIO:
Set `output_dir="/root/runs"` without root access. `mkdir` raises `PermissionError`.

IMPACT:
Crash with generic error. No data loss.

FIX DIRECTION:
```python
try:
    run_dir.mkdir(parents=True, exist_ok=True)
except OSError as e:
    raise OSError(f"ExperimentTrackerNode: cannot create run directory '{run_dir}': {e}") from e
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | MLflow backend unavailability causes hard pipeline failure with no fallback to JSON backend |
