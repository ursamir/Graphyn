# Data Flow and Workspace Layout

---

## Pipeline Data Flow (End-to-End)

```
User (CLI / SDK / API / MCP)
    │
    │  1. Provide pipeline IR JSON
    ▼
get_backend().execute(graph, ...)   ← canonical entry point
    │
    ▼
LocalPythonBackend → orchestrator.run_pipeline_ir_async(graph, ...)
    │
    ├─ load_ir(data) → GraphIR
    │
    ├─ _ir_to_pipeline_config() → PipelineConfig
    │
    ├─ PipelineGraph(config)
    │      ├─ instantiate Node objects from registry
    │      ├─ validate edges (CompatibilityChecker)
    │      └─ topological sort + wave computation
    │
    ├─ RunManager() → workspace/runs/{run_id}/
    │      └─ writes meta.json (status: "running")
    │
    ├─ register_active_run(run)   ← run_control.py
    │
    ├─ For each node in topo order:
    │      ├─ assemble inputs from upstream outputs
    │      ├─ evaluate edge conditions
    │      ├─ [cache check] → skip process() on hit
    │      ├─ NodeExecutor.execute(inputs)
    │      │      ├─ node.on_start()
    │      │      ├─ node.process(inputs) → outputs
    │      │      └─ node.on_end()
    │      ├─ [cache save]
    │      └─ [checkpoint write if checkpoint=True]
    │
    ├─ RunManager.save_logs() → workspace/runs/{run_id}/logs.json
    ├─ RunManager.save_metadata() → workspace/runs/{run_id}/meta.json (status: "completed")
    └─ deregister_active_run(run_id)
```

---

## `AudioSample` Lifecycle

`AudioSample` is the primary data type flowing between audio nodes. It is a Pydantic `PortDataType` subclass.

```python
class AudioSample(PortDataType):
    path: str
    sample_rate: int
    data: Optional[Any] = None   # numpy float32 ndarray
    label: str = ""
    metadata: dict[str, Any] = {}
```

**Through the pipeline (plugin nodes):**

```
dataset_ingest.process()
    └─ librosa.load(file) → AudioSample(path, sr, data, label, metadata={})

audio_conditioner.process(samples)
    └─ resample + normalize → sample.model_copy() + data.copy()
                               (not deepcopy — performance fix)
                               metadata={conditioned, conditioning, clipped}

segmenter.process(samples)
    └─ slice data → AudioSample(same path, same sr, chunk, same label,
                                metadata={parent, start, end, segment_id})

augmentation_pipeline.process(samples)
    └─ original + N copies → AudioSample(..., metadata={augmented, gain_db, augmentation_id})

feature_frontend.process(samples)
    └─ librosa features → FeatureArray(data, label, feature_type, metadata)

dataset_builder.process(features)
    └─ split into train/val/test → DatasetArtifact(X_train, y_train, ...)
```

---

## Workspace Directory Layout

```
workspace/
├── datasets/
│   ├── input/
│   │   ├── {label}/           # Audio files organized by label
│   │   │   ├── file1.wav
│   │   │   └── file2.mp3
│   │   ├── mic/               # Mic recordings uploaded via browser
│   │   │   └── mic_20240101_120000_000000.wav
│   │   └── uploads/           # Files uploaded via POST /api/v1/data/inputs/upload
│   │       └── upload_20240101_120000_000000.wav
│   └── output/
│       └── {project}/
│           ├── project.json       # Project metadata
│           ├── taxonomy.json      # Label hierarchy
│           ├── contract.json      # Quality constraints
│           ├── spec.md            # Free-form specification
│           ├── annotations.jsonl  # Per-sample annotations
│           ├── curation_decisions.json
│           ├── quality_report.json
│           ├── snapshots/
│           │   └── {snapshot_name}/
│           └── {version}/         # e.g. v1, v2, v1.0.0
│               ├── train/
│               │   └── {label}/
│               │       └── {hash_id}.wav
│               ├── val/
│               │   └── {label}/
│               │       └── {hash_id}.wav
│               ├── test/
│               │   └── {label}/
│               │       └── {hash_id}.wav
│               ├── labels.csv     # id, path, label, split
│               ├── metadata.json  # Full sample metadata
│               └── pipeline.yaml  # Pipeline config snapshot (if pipeline_config set)
├── runs/
│   └── {run_id}/              # full 32-char UUID4 hex
│       ├── meta.json          # {run_id, created_at, status, duration_s, num_nodes, node_stats}
│       ├── logs.json          # All log entries
│       ├── graph.json         # GraphIR JSON (always written)
│       ├── resume_state.json  # written when checkpoint=True
│       └── checkpoints/       # Only when checkpoint=True
│           └── node_{node_id}/
│               ├── port_{name}/
│               │   ├── {0..n}.wav
│               │   └── manifest.json
│               └── manifest.json
├── artifacts/
│   └── {artifact_id}/
│       ├── record.json
│       └── data/
│           ├── manifest.json
│           └── *.wav
├── provenance/
│   ├── {artifact_id}.json
│   └── by_run/{run_id}.json
├── cache/
│   └── {sha256}/              # Cache key = SHA-256(node_type+config+input_hash)
│       ├── port_{name}/
│       │   ├── {0..n}.wav
│       │   └── manifest.json
│       └── manifest.json
├── configs/
│   └── templates/
│       ├── basic-wakeword.graph.json
│       ├── speech-recognition.graph.json
│       ├── audio-classification.graph.json
│       ├── audio-quality-check.graph.json
│       └── podcast-leveling.graph.json
└── webhooks.json              # {url, events}
```

---

## `labels.csv` Format

```csv
id,path,label,split
a1b2c3d4e5f6,train/wakeword/a1b2c3d4e5f6.wav,wakeword,train
b2c3d4e5f6a1,val/wakeword/b2c3d4e5f6a1.wav,wakeword,val
```

The `id` is a 16-character hex string derived from `stable_hash(path, len(data), label, start, end, augmented, augmentation_id)`.

---

## Pipeline IR JSON Format

The canonical format is IR JSON (`.graph.json`). YAML is deprecated — use `graphyn migrate --config pipeline.yaml` to convert.

```json
{
  "schema_version": "1.1",
  "metadata": {"name": "my-pipeline", "seed": 42},
  "nodes": [
    {"id": "ingest_0", "node_type": "dataset_ingest",    "config": {"path": "workspace/datasets/input/speech"}},
    {"id": "cond_0",   "node_type": "audio_conditioner", "config": {"sample_rate": 16000}},
    {"id": "seg_0",    "node_type": "segmenter",         "config": {"mode": "vad"}},
    {"id": "feat_0",   "node_type": "feature_frontend",  "config": {"feature_type": "mfcc"}},
    {"id": "ds_0",     "node_type": "dataset_builder",   "config": {"split_ratios": {"train": 0.8, "val": 0.1, "test": 0.1}}}
  ],
  "edges": [
    {"src_id": "ingest_0", "src_port": "output", "dst_id": "cond_0",  "dst_port": "input"},
    {"src_id": "cond_0",   "src_port": "output", "dst_id": "seg_0",   "dst_port": "input"},
    {"src_id": "seg_0",    "src_port": "output", "dst_id": "feat_0",  "dst_port": "input"},
    {"src_id": "feat_0",   "src_port": "output", "dst_id": "ds_0",    "dst_port": "input"}
  ]
}
```

---

## Streaming Protocol (`POST /api/v1/pipelines/run`)

The server writes one JSON object per line (NDJSON). The client reads the response body as a stream and parses each line.

```jsonc
// Structured events
{"type": "pipeline_start", "total_nodes": 5, "timestamp": "2024-01-01T00:00:00+00:00"}
{"type": "node_start", "node_type": "InputNode", "node_index": 0, "total_nodes": 5, "timestamp": "..."}
{"type": "node_end", "node_type": "InputNode", "node_index": 0, "duration": 0.123, "output_count": 42, "timestamp": "..."}
{"type": "node_error", "node_type": "CleanNode", "node_index": 1, "error_message": "...", "error_type": "ValueError", "timestamp": "..."}
{"type": "pipeline_summary", "timestamp": "..."}
{"type": "done", "timestamp": "2024-01-01T00:00:01+00:00"}

// On pipeline failure
{"type": "error", "timestamp": "...", "error_type": "ValueError", "message": "..."}

// Plain-text log entries (interleaved)
{"time": "2024-01-01T00:00:00+00:00", "level": "INFO", "message": "[0] InputNode — starting"}
```

All timestamps are UTC-aware ISO 8601 strings ending in `+00:00`.

---

## Ingestion SSE Protocol (`/api/v1/ingest/*/stream`)

Uses Server-Sent Events format (`data: {...}\n\n`):

```
data: {"type": "progress", "url": "https://...", "status": "success", "message": "Downloaded to ..."}

data: {"type": "progress", "url": "https://...", "status": "error", "message": "Download failed: ..."}

data: {"type": "summary", "total_files": 3, "total_duration_seconds": 12.5, "label_distribution": {"speech": 3}}
```

---

## Security Boundaries

- `InputNode` and `MicInputNode` validate that `path` is inside `workspace/datasets/input/` using `os.path.commonpath`.
- `ExportNode` validates that the output path stays inside `workspace/datasets/output/` and that `project` and `version` match `^[a-zA-Z0-9_\-]+$`.
- All API endpoints that accept path components use `_safe_child()` to prevent path traversal.
- Template names are validated against `^[A-Za-z0-9_-]+$`.
- Run IDs are validated as alphanumeric before filesystem access.
- CORS is restricted to localhost origins only.
- Uploaded filenames are replaced with timestamped names to prevent path injection.
- Ingestion download filenames are prefixed with a UUID to prevent collisions and path traversal.
- `GRAPHYN_PLUGIN_ALLOWED_SOURCES` — comma-separated URL prefix allowlist for plugin installs; empty = allow all.
- Run IDs validated against ASCII-only alphanumeric regex before any filesystem access.
