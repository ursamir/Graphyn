# Domain Services

Services in `app/domain/` are domain-specific (audio ML) and depend on platform infrastructure but are not part of the platform core. Platform code never imports from `app/domain/` — domain code registers into platform registries at startup.

**See also:** [ARCHITECTURE.md](./ARCHITECTURE.md) | [BACKEND_CORE.md](./BACKEND_CORE.md) | [DATA_FLOW_AND_WORKSPACE.md](./DATA_FLOW_AND_WORKSPACE.md)

---

## Table of Contents

1. [IngestionService](#1-ingestionservice)
2. [ProjectManager](#2-projectmanager)
3. [QualityChecker](#3-qualitychecker)
4. [AudioSampleHandler](#4-audiosamplehandler)

---

## 1. IngestionService

**File:** `app/domain/ingestion.py`

Downloads audio from URLs or HuggingFace datasets into `workspace/datasets/input/`. All jobs run in background daemon threads and expose a streaming progress interface for SSE consumers.

### Job Lifecycle

```
start_url_job(urls, label)   → job_id (immediate)
start_hf_job(repo_id, ...)   → job_id (immediate)
         │
         ▼
Background thread runs _run_url_job() or _run_hf_job()
         │
         ├── appends progress events to IngestionJob.progress
         ├── sets job.status = "running" → "completed" | "failed"
         └── flushes final state to Redis (if GRAPHYN_REDIS_URL set)
         │
         ▼
get_job(job_id)              → IngestionJob (in-process or Redis)
stream_job(job_id)           → Generator[dict, None, None]
```

### Public API

| Method | Description |
|---|---|
| `start_url_job(urls, label)` | Download each URL to `input/{label}/`. Returns `job_id`. |
| `start_hf_job(repo_id, split, audio_col, label_col, label_override)` | Stream a HuggingFace dataset. Returns `job_id`. |
| `get_job(job_id)` | Return `IngestionJob`. Checks in-process dict first, then Redis. Raises `KeyError` if not found. |
| `stream_job(job_id)` | Yield progress events as they arrive. Re-fetches job on each iteration for live Redis state. |

### `IngestionJob` Model

```python
class IngestionJob(BaseModel):
    job_id: str
    status: str          # "running" | "completed" | "failed"
    progress: list[dict] # append-only event list

    def append_progress(event: dict) -> None   # thread-safe
    def set_status(status: str) -> None        # thread-safe
    def read_progress() -> list[dict]          # thread-safe snapshot
```

### Progress Event Schema

| `type` | Fields | Meaning |
|---|---|---|
| `"progress"` | `url`, `status` (`"success"` \| `"error"` \| `"warning"`), `message` | Per-file result |
| `"summary"` | `total_files`, `total_duration_seconds`, `label_distribution` | Final summary |
| `"error"` | `message` | Fatal job error (missing dep, dataset load failure) |

### Security & Limits

- Labels sanitized via `_sanitize_label()` — strips non-alphanumeric/hyphen/underscore, truncates to 64 chars, defaults to `"default"` if empty.
- Download size capped at **500 MB** per file. File is unlinked before raising if limit exceeded.
- HuggingFace label paths validated with `is_relative_to(BASE_INPUT)` to prevent path traversal.
- Filenames prefixed with 8-char UUID hex to prevent collisions and path traversal.

### Scalability

When `GRAPHYN_REDIS_URL` is set, completed job state is persisted to Redis (`graphyn:ingest_job:{id}`, `graphyn:ingest_events:{id}`, 24h TTL). `get_job()` checks in-process dict first (fast path), then falls back to Redis for cross-worker streaming. Running jobs always execute on the worker that started them.

### Supported Extensions

`.wav`, `.mp3`, `.flac`, `.ogg`, `.m4a`

---

## 2. ProjectManager

**File:** `app/domain/project_manager.py`

Full project lifecycle for audio dataset projects stored under `workspace/datasets/output/{project}/`.

### Project Directory Layout

```
workspace/datasets/output/{project}/
├── project.json          # name, status, created_at, updated_at, versions[]
├── taxonomy.json         # hierarchical label tree
├── contract.json         # quality constraints (min/max duration, sample rate, SNR)
├── spec.md               # free-form project specification
├── annotations.jsonl     # one JSON object per line, keyed by sample_path
├── curation_decisions.json  # {path: {decision, timestamp}}
├── quality_report.json   # written by QualityChecker.run()
├── snapshots/            # named working-state snapshots
│   └── {snapshot_name}/  # copy of working files at snapshot time
└── {version}/            # e.g. v1, v1.0.0
    ├── metadata.json
    ├── lineage.json
    ├── labels.csv
    └── {split}/{label}/{hash}.wav
```

### Public API

**Project lifecycle:**

| Method | Description |
|---|---|
| `create(name)` | Create project directory + `project.json`. Raises `ValueError` if exists. |
| `rename(name, new_name)` | Move directory, update `project.json`. |
| `delete(name, confirm)` | Remove directory. `confirm` must equal `name`. |
| `set_status(name, status)` | Update status. Valid: `"draft"`, `"in-progress"`, `"ready"`, `"archived"`. |
| `clone(name, new_name)` | Copy metadata files only (no audio). Fresh `project.json` for clone. |
| `list_all()` | Return all `project.json` contents. Skips corrupt files with a warning. |

**Taxonomy:**

| Method | Description |
|---|---|
| `set_taxonomy(name, tree)` | Write `taxonomy.json`. Validates sibling-scope uniqueness recursively. |
| `get_taxonomy(name)` | Read `taxonomy.json`. Returns `[]` if not found. |

**Contract:**

| Method | Description |
|---|---|
| `set_contract(name, contract)` | Write `contract.json`. Validates `min_duration_ms < max_duration_ms`. |
| `get_contract(name)` | Read `contract.json`. Returns `{}` if not found. |

**Spec:**

| Method | Description |
|---|---|
| `set_spec(name, markdown)` | Write `spec.md`. |
| `get_spec(name)` | Read `spec.md`. Returns `""` if not found. |

**Annotations:**

| Method | Description |
|---|---|
| `add_annotations(name, annotations)` | Append/overwrite `annotations.jsonl` by `sample_path`. |
| `get_annotations(name)` | Read all annotation records. |
| `export_annotations(name, fmt)` | Return JSONL or CSV string. |
| `import_annotations(name, content, fmt)` | Parse JSONL/CSV, validate, merge. Returns `{imported, invalid, errors}`. |
| `validate_annotations(name)` | Returns `{total_samples, annotated_count, unannotated_count, missing_labels}`. Normalizes absolute paths to project-relative. |
| `bulk_annotate(name, paths, label)` | Assign label to all specified paths as whole-file annotations. |

**Curation:**

| Method | Description |
|---|---|
| `add_curation_decision(name, path, decision)` | Write to `curation_decisions.json`. |
| `get_curation_decisions(name)` | Read as list of `{sample_path, decision, timestamp}`. |

**Versions:**

| Method | Description |
|---|---|
| `list_versions(name)` | List subdirs matching `v<N>` or `v<N>.<N>[.<N>...]`. |
| `restore_version(name, version)` | Copy version contents to project root. Atomic: temp dir + rename. Validates version string against regex. |
| `get_lineage(name, version)` | Read `{version}/lineage.json`. |
| `diff_versions(name, version_a, version_b)` | Compare `labels.csv` files. Returns `{added, removed, changed}`. |

**Snapshots:**

| Method | Description |
|---|---|
| `create_snapshot(name, snapshot_name)` | Copy working files to `snapshots/{snapshot_name}/`. Validates name. |
| `list_snapshots(name)` | List snapshot subdirs. |
| `restore_snapshot(name, snapshot_name)` | Copy snapshot back to project root. Atomic: temp dir + rename. |

**Dataset stats:**

| Method | Description |
|---|---|
| `get_stats(name, version)` | Compute `{total_samples, total_duration_s, label_distribution, sample_rate_distribution, duration_histogram, snr_histogram, class_imbalance_warning, imbalanced_labels}`. |

### Validation Rules

- Project/snapshot names: `^[\w\-]{1,128}$` — letters, digits, hyphens, underscores only.
- Version strings: `^v\d+(\.\d+)*$` — validated before any path construction.
- `min_duration_ms` must be strictly less than `max_duration_ms` in contract.
- `validate_annotations` normalizes absolute annotation keys to project-relative paths.

---

## 3. QualityChecker

**File:** `app/domain/quality_checker.py`

Automated quality checks for audio dataset versions. Persists findings to `quality_report.json`. Never raises — all errors are recorded as findings.

### Usage

```python
from app.domain.quality_checker import QualityChecker

checker = QualityChecker()
findings = checker.run("my_project", "v1")
# findings: list[dict] — each dict is a finding record
```

### `run(project, version, contract=None)` → `list[dict]`

Runs all checks on `workspace/datasets/output/{project}/{version}/`. If `contract` is `None`, loads `contract.json` from the project directory automatically. Persists results to `quality_report.json` before returning.

### Checks

| Check | Trigger | Severity |
|---|---|---|
| `duration_range` | Duration outside `contract.min_duration_ms` / `max_duration_ms` | `error` |
| `sample_rate` | Sample rate ≠ `contract.required_sample_rate` | `error` |
| `clipping` | Peak amplitude > 0.999 | `warning` |
| `dc_offset` | `abs(mean(audio)) > 0.01` | `warning` |
| `snr` | Estimated SNR < `contract.snr_threshold_db` (default 10 dB) | `warning` |
| `duplicates` | SHA-256 of first 30s resampled to 16 kHz mono matches a prior file | `warning` |
| `outliers` | Value outside mean ± 3σ for duration, peak amplitude, or spectral centroid | `warning` |
| `class_imbalance` | Label count < 20% of mean label count | `warning` |
| `load_error` | File cannot be loaded by librosa or soundfile | `error` |
| `internal_error` | Unexpected exception during the check run | `error` |

### Finding Schema

```json
{
  "sample_path": "v1/train/speech/abc123.wav",
  "check_name": "snr",
  "severity": "warning",
  "detail": "Estimated SNR 7.3 dB is below threshold 10.0 dB"
}
```

### SNR Estimation

Uses the first `noise_profile_ms` milliseconds (default 100ms) as the noise floor estimate. Signal power is computed from the remaining audio. This assumes the file starts with background noise — files that start with speech will produce misleadingly low SNR estimates. For accurate results, set `noise_profile_ms` in the contract to match the actual silence region length.

### Contract Fields Used

| Field | Default | Used by |
|---|---|---|
| `min_duration_ms` | — | `duration_range` |
| `max_duration_ms` | — | `duration_range` |
| `required_sample_rate` | — | `sample_rate` |
| `snr_threshold_db` | `10.0` | `snr` |
| `noise_profile_ms` | `100.0` | `snr` |

### Output File

`workspace/datasets/output/{project}/quality_report.json`:

```json
{
  "findings": [
    {"sample_path": "...", "check_name": "...", "severity": "...", "detail": "..."}
  ]
}
```

---

## 4. AudioSampleHandler

**File:** `app/models/audio_artifact_serializer.py`

Domain-side implementation of `ArtifactTypeHandler` for the `"audio_samples"` artifact type. Owns all WAV I/O, manifest format, and `AudioSample` duck-typing logic.

### Registration

Called once at application startup from each entry point:

```python
from app.models.audio_artifact_serializer import register_audio_serializer
register_audio_serializer()
```

Idempotent — safe to call multiple times.

### Manifest Format

Written to `artifacts/{id}/data/` and `cache/port_{name}/`:

```
manifest.json
{
  "samples": [
    {
      "filename": "0.wav",
      "label": "speech",
      "path": "/original/source/path.wav",
      "sample_rate": 16000,
      "metadata": {}
    }
  ]
}
```

WAV files are written alongside `manifest.json` in the same directory.

### `ArtifactTypeHandler` Methods

| Method | Description |
|---|---|
| `serialize(data, dest_dir)` | Write `list[AudioSample]` to `dest_dir` as WAV + `manifest.json`. Writes to a temp dir first, then atomically renames. Cleans up temp dir on failure. |
| `deserialize(src_dir)` | Read WAV + `manifest.json` → `list[AudioSample]`. Returns `None` if manifest missing (cache miss). Skips corrupt WAV files with a warning. |
| `compute_content_hash_input(data)` | Return stable JSON string for SHA-256 hashing. Includes path, sample rate, shape, label, and a 16-char PCM hash of the first 1024 float32 values. |
| `infer_type(value)` | Return `"audio_samples"` if value is a non-empty `list[AudioSample]`. Uses exact type check first, duck-type fallback (`.data` + `.sample_rate`). |

### Platform Integration

The platform calls `get_serializer_registry().get("audio_samples")` to obtain the handler. Platform code (`artifact_store`, `pipeline_cache`, `checkpoint`) never imports `AudioSample` directly — all type-specific logic is encapsulated in this handler.

**See also:** [BACKEND_CORE.md — ArtifactSerializerRegistry](./BACKEND_CORE.md#artifactserializerregistry)
