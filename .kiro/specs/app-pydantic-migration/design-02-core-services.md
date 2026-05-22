# Design Sub-File 02 — Core Services

← Back to [design.md](design.md)

This sub-file covers the migration of:
1. `app/core/logger.py` — fix deprecated `datetime.utcnow()`, clean up `node_end` signature
2. `app/core/run_manager.py` — fix deprecated `datetime.utcnow()`
3. `app/core/ingestion.py` — migrate `IngestionJob` from `@dataclass` to Pydantic `BaseModel`
4. `app/core/pipeline_cache.py` — use `AudioSample.model_validate()` in `load()`

---

## 1. PipelineLogger — UTC Timestamps and node_end Cleanup

### Current Implementation

```python
# app/core/logger.py (BEFORE — relevant excerpts)
import re
import time
from datetime import datetime
from queue import Queue


class PipelineLogger:
    def _timestamp(self):
        return datetime.utcnow().isoformat()  # ❌ deprecated, naive datetime

    def pipeline_start(self, total_nodes: int):
        self.info(f"Pipeline starting — {total_nodes} node{'s' if total_nodes != 1 else ''}")
        self._emit_structured({
            "type": "pipeline_start",
            "total_nodes": total_nodes,
            "timestamp": datetime.utcnow().isoformat() + "Z",  # ❌ deprecated
        })

    def node_start(self, node_type, index, total_nodes=None):
        self.info(f"[{index}] {node_type} — starting")
        event = {
            "type": "node_start",
            "node_type": node_type,
            "node_index": index,
            "timestamp": datetime.utcnow().isoformat() + "Z",  # ❌ deprecated
        }
        if total_nodes is not None:
            event["total_nodes"] = total_nodes
        self._emit_structured(event)

    def node_end(self, node_type, index, duration, count_str=""):  # ❌ string param
        self.info(f"[{index}] {node_type} — done in {duration:.3f}s{count_str}")
        # Parse the leading integer from count_str (e.g. " → 3 samples" → 3)
        match = re.search(r"\d+", count_str)  # ❌ regex parsing
        output_count = int(match.group()) if match else 0
        self._emit_structured({
            "type": "node_end",
            "node_type": node_type,
            "node_index": index,
            "duration": duration,
            "output_count": output_count,
            "timestamp": datetime.utcnow().isoformat() + "Z",  # ❌ deprecated
        })

    def node_error(self, node_type, index, error):
        self.error(f"[{index}] {node_type} — FAILED: {error}")
        self._emit_structured({
            "type": "node_error",
            ...
            "timestamp": datetime.utcnow().isoformat() + "Z",  # ❌ deprecated
        })

    def pipeline_summary(self, stats_dict: dict):
        self._emit_structured({
            "type": "pipeline_summary",
            **stats_dict,
            "timestamp": datetime.utcnow().isoformat() + "Z",  # ❌ deprecated
        })
```

**Problems**:
- `datetime.utcnow()` is deprecated in Python 3.12 and produces naive datetimes.
- `node_end` accepts a `count_str` string and uses `re.search` to extract an integer from it.
- `import re` is only used for this one regex call.

### New Implementation

```python
# app/core/logger.py (AFTER)
import time
from datetime import datetime, timezone  # ✅ added timezone
from queue import Queue


class PipelineLogger:
    def __init__(self, queue: Queue | None = None):
        self.logs = []
        self.start_time = time.time()
        self.queue = queue

    def _timestamp(self):
        return datetime.now(timezone.utc).isoformat()  # ✅ UTC-aware

    def _emit(self, entry):
        self.logs.append(entry)
        print(f"[{entry['time']}] [{entry['level']}] {entry['message']}")
        if self.queue:
            self.queue.put(entry)

    def _emit_structured(self, entry: dict):
        self.logs.append(entry)
        if self.queue:
            self.queue.put(entry)

    def log(self, level, message):
        entry = {
            "time": self._timestamp(),
            "level": level,
            "message": message,
        }
        self._emit(entry)

    def info(self, msg):
        self.log("INFO", msg)

    def error(self, msg):
        self.log("ERROR", msg)

    def pipeline_start(self, total_nodes: int):
        self.info(f"Pipeline starting — {total_nodes} node{'s' if total_nodes != 1 else ''}")
        self._emit_structured({
            "type": "pipeline_start",
            "total_nodes": total_nodes,
            "timestamp": self._timestamp(),  # ✅ uses _timestamp()
        })

    def node_start(self, node_type, index, total_nodes=None):
        self.info(f"[{index}] {node_type} — starting")
        event = {
            "type": "node_start",
            "node_type": node_type,
            "node_index": index,
            "timestamp": self._timestamp(),  # ✅ uses _timestamp()
        }
        if total_nodes is not None:
            event["total_nodes"] = total_nodes
        self._emit_structured(event)

    def node_end(self, node_type, index, duration, output_count: int = 0):  # ✅ int param
        count_str = f" → {output_count} samples" if output_count else ""
        self.info(f"[{index}] {node_type} — done in {duration:.3f}s{count_str}")  # ✅ uses int directly
        self._emit_structured({
            "type": "node_end",
            "node_type": node_type,
            "node_index": index,
            "duration": duration,
            "output_count": output_count,  # ✅ integer, no regex
            "timestamp": self._timestamp(),  # ✅ uses _timestamp()
        })

    def node_error(self, node_type, index, error):
        self.error(f"[{index}] {node_type} — FAILED: {error}")
        self._emit_structured({
            "type": "node_error",
            "node_type": node_type,
            "node_index": index,
            "error_message": str(error),
            "error_type": type(error).__name__,
            "timestamp": self._timestamp(),  # ✅ uses _timestamp()
        })

    def pipeline_summary(self, stats_dict: dict):
        self._emit_structured({
            "type": "pipeline_summary",
            **stats_dict,
            "timestamp": self._timestamp(),  # ✅ uses _timestamp()
        })

    def summary(self):
        total = time.time() - self.start_time
        self.info(f"Pipeline completed in {total:.3f}s")
```

**Changes**:
- ✅ `import re` removed
- ✅ `from datetime import timezone` added
- ✅ All `datetime.utcnow()` replaced with `datetime.now(timezone.utc)`
- ✅ All inline timestamp calls replaced with `self._timestamp()`
- ✅ `node_end` signature: `count_str=""` → `output_count: int = 0`
- ✅ `node_end` log line uses `output_count` directly, no regex

### Impact on Callers

The `node_end` signature change affects two callers:

1. **`app/core/pipeline.py` (new DAG executor)** — already calls `logger.node_end(node_type, idx, node_duration)` with no fourth argument. This is fine since `output_count` defaults to `0`.

2. **`app/core/pipeline.py` (legacy `run_pipeline` if present)** — any call passing `count_str` as a positional string argument must be updated to pass `output_count` as an integer. The legacy `_count_payload` helper returns a string; use `_payload_count` instead which returns an integer.

3. **`app/api/main.py` (streaming endpoint)** — the `run_pipeline_stream` function creates a `PipelineLogger` and does not override `node_end`, so no change needed there.

4. **`app/cli/main.py` (StdoutLogger)** — the `StdoutLogger` subclass overrides `_emit` but not `node_end`, so it reads `event.get("output_count", "")` from the structured event. This already works correctly with the integer value.

---

## 2. RunManager — UTC Timestamps

### Current Implementation

```python
# app/core/run_manager.py (BEFORE — relevant excerpts)
from datetime import datetime

class RunManager:
    def __init__(self, base_dir: str | None = None):
        ...
        self._write_meta({
            "run_id": self.run_id,
            "created_at": datetime.utcnow().isoformat(),  # ❌ deprecated
            "status": "running",
        })

    def save_metadata(self, metadata: dict):
        duration = time.time() - self._start_time
        full = {
            "run_id": self.run_id,
            "created_at": datetime.utcnow().isoformat(),  # ❌ deprecated
            "duration_s": round(duration, 3),
            "status": "completed",
            **metadata,
        }
        self._write_meta(full)
```

### New Implementation

```python
# app/core/run_manager.py (AFTER — relevant excerpts)
from datetime import datetime, timezone  # ✅ added timezone

class RunManager:
    def __init__(self, base_dir: str | None = None):
        ...
        self._write_meta({
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),  # ✅ UTC-aware
            "status": "running",
        })

    def save_metadata(self, metadata: dict):
        duration = time.time() - self._start_time
        full = {
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),  # ✅ UTC-aware
            "duration_s": round(duration, 3),
            "status": "completed",
            **metadata,
        }
        self._write_meta(full)
```

**Changes**:
- ✅ `from datetime import timezone` added to existing import
- ✅ Both `datetime.utcnow()` calls replaced with `datetime.now(timezone.utc)`

### Migration Notes

- The `isoformat()` output changes from `"2024-01-15T10:30:00.123456"` (naive) to `"2024-01-15T10:30:00.123456+00:00"` (UTC-aware). This is a backward-compatible change for any consumer that parses ISO 8601 strings.
- The `mark_failed` method does not call `datetime.utcnow()` — it reads existing meta and updates it — so no change is needed there.

---

## 3. IngestionJob — Dataclass to Pydantic BaseModel

### Current Implementation

```python
# app/core/ingestion.py (BEFORE — relevant excerpt)
from dataclasses import dataclass, field

@dataclass
class IngestionJob:
    job_id: str
    status: str  # "running" | "completed" | "failed"
    progress: list[dict] = field(default_factory=list)
```

### New Implementation

```python
# app/core/ingestion.py (AFTER — relevant excerpt)
from pydantic import BaseModel, Field

class IngestionJob(BaseModel):
    job_id: str
    status: str  # "running" | "completed" | "failed"
    progress: list[dict] = Field(default_factory=list)
```

**Changes**:
- ✅ `from dataclasses import dataclass, field` removed
- ✅ `from pydantic import BaseModel, Field` added
- ✅ `@dataclass` decorator removed
- ✅ `field(default_factory=list)` → `Field(default_factory=list)`
- ✅ `class IngestionJob(BaseModel)` instead of `class IngestionJob`

### Behavioral Compatibility

The `IngestionService` methods mutate `job.progress` by calling `job.progress.append(...)`. This works identically with Pydantic `BaseModel` because:
- Pydantic v2 `BaseModel` fields are mutable by default (`frozen=False`)
- `list[dict]` fields are stored as regular Python lists
- `job.progress.append({...})` works exactly as before

The `stream_job` generator reads `job.progress` and `job.status` by attribute access — unchanged.

New capability: `job.model_dump()` returns a serialisable dict, enabling JSON serialisation without custom code.

### Migration Notes

- `IngestionJob` does not inherit from `NodeConfig` (which has `extra="forbid"`). It inherits directly from `pydantic.BaseModel` with default settings, so extra fields are ignored rather than rejected.
- The `_jobs` module-level dict stores `IngestionJob` instances — no change needed there.
- The `IngestionService.get_job()` return type annotation remains `IngestionJob` — no change.

---

## 4. PipelineCache — AudioSample.model_validate()

### Current Implementation

```python
# app/core/pipeline_cache.py (BEFORE — load() excerpt)
def load(self, cache_key: str) -> Optional[list]:
    cache_dir = self._cache_dir(cache_key)
    manifest_path = cache_dir / "manifest.json"

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        samples = []
        for entry in manifest["samples"]:
            wav_path = cache_dir / entry["filename"]
            data, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=False)
            sample = AudioSample(  # ❌ direct constructor call
                path=entry["path"],
                sample_rate=entry["sample_rate"],
                data=data,
                label=entry["label"],
                metadata=entry.get("metadata", {}),
            )
            samples.append(sample)

        return samples

    except Exception as exc:
        logger.warning(
            "Cache read failed for key %s (%s: %s) — will re-execute node",
            cache_key,
            type(exc).__name__,
            exc,
        )
        return None
```

**Problems**:
- Uses `AudioSample(...)` constructor directly instead of `model_validate()`
- Does not distinguish between `pydantic.ValidationError` (corrupt data) and other exceptions (I/O errors)

### New Implementation

```python
# app/core/pipeline_cache.py (AFTER — load() excerpt)
import pydantic  # ✅ added for ValidationError

def load(self, cache_key: str) -> Optional[list]:
    cache_dir = self._cache_dir(cache_key)
    manifest_path = cache_dir / "manifest.json"

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        samples = []
        for entry in manifest["samples"]:
            wav_path = cache_dir / entry["filename"]
            data, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=False)
            try:
                sample = AudioSample.model_validate({  # ✅ model_validate
                    "path": entry["path"],
                    "sample_rate": entry["sample_rate"],
                    "data": data,
                    "label": entry["label"],
                    "metadata": entry.get("metadata", {}),  # ✅ default to {}
                })
            except pydantic.ValidationError as exc:  # ✅ specific exception
                logger.warning(
                    "Cache entry validation failed for key %s (%s) — will re-execute node",
                    cache_key,
                    exc,
                )
                return None
            samples.append(sample)

        return samples

    except Exception as exc:
        logger.warning(
            "Cache read failed for key %s (%s: %s) — will re-execute node",
            cache_key,
            type(exc).__name__,
            exc,
        )
        return None
```

**Changes**:
- ✅ `import pydantic` added
- ✅ `AudioSample(...)` → `AudioSample.model_validate({...})`
- ✅ `entry.get("metadata", {})` used to default missing `metadata` key
- ✅ `pydantic.ValidationError` caught specifically, logs warning, returns `None`

### save() Method

The `save()` method already uses attribute access (`sample.label`, `sample.path`, `sample.sample_rate`, `sample.metadata`) — no changes needed.

### Migration Notes

- `AudioSample.model_validate()` applies the `_coerce_data` validator which converts `None` → empty float32 array. This is the same behavior as the direct constructor call.
- The outer `except Exception` block is preserved to handle I/O errors (file not found, JSON parse errors, etc.).
- The inner `pydantic.ValidationError` catch is new — it specifically handles corrupt manifest data and returns `None` to trigger node re-execution.

---

## Before/After Summary

| File | Lines Changed | Key Changes |
|------|---------------|-------------|
| `app/core/logger.py` | ~20 | Remove `import re`; add `timezone`; replace all `utcnow()`; change `node_end` signature |
| `app/core/run_manager.py` | ~4 | Add `timezone`; replace 2× `utcnow()` |
| `app/core/ingestion.py` | ~6 | Replace `@dataclass` + `field` with `BaseModel` + `Field` |
| `app/core/pipeline_cache.py` | ~12 | Add `import pydantic`; use `model_validate`; add `ValidationError` catch |

---

## Testing

**Unit tests** (in `tests/test_migration.py`):
- `test_logger_no_utcnow()` — assert `datetime.utcnow` not called (mock)
- `test_logger_node_end_integer()` — assert `node_end(..., output_count=5)` emits `{"output_count": 5}`
- `test_run_manager_created_at_utc()` — assert `meta.json` `created_at` ends with `+00:00`
- `test_ingestion_job_is_pydantic()` — assert `issubclass(IngestionJob, BaseModel)`
- `test_ingestion_job_progress_append()` — assert `job.progress.append({})` works
- `test_ingestion_job_model_dump()` — assert `job.model_dump()` returns dict
- `test_pipeline_cache_load_validation_error()` — mock `model_validate` to raise `ValidationError`, assert `load()` returns `None`

**Property tests** (in `tests/test_properties.py`):
- `test_property_4_utc_timestamp_format()` — Property 4 (UTC timestamp format)
- `test_property_5_node_end_output_count()` — Property 5 (node_end output_count passthrough)
- `test_property_6_node_end_log_line()` — Property 6 (node_end log line completeness)
- `test_property_7_run_manager_utc()` — Property 7 (RunManager UTC timestamp)
- `test_property_8_ingestion_job_default_progress()` — Property 8 (IngestionJob default progress)
- `test_property_9_ingestion_job_roundtrip()` — Property 9 (IngestionJob serialisation round-trip)
- `test_property_10_audio_sample_metadata()` — Property 10 (AudioSample metadata round-trip)
