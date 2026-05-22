# AudioBuilder — Examples

This directory contains **21 production-grade examples** that cover the full feature set of the platform — from audio ML pipelines to agent-native MCP operation, parallel execution, provenance tracking, plugin development, and general-purpose workflow execution.

---

## Quick Start

```bash
# 1. Prepare the dataset (run once)
venv/bin/python examples/prepare_real_data.py

# 2. Run your first example
venv/bin/python examples/01_wake_word/run_sdk.py

# 3. Explore the platform features
venv/bin/python examples/07_mcp_agent_pipeline/agent.py
venv/bin/python examples/09_parallel_execution/parallel_pipeline.py
```

---

## Feature Coverage Map

Use this table to find the example that demonstrates a specific feature:

| Feature | Example |
|---|---|
| Basic audio preprocessing | 01, 02, 03, 04, 05 |
| Custom plugin nodes | 02, 03, 04, 05, 14 |
| End-to-end ML training (TFLite) | 06 |
| MCP agent loop (discover → build → execute) | 07 |
| REST API streaming (NDJSON) | 08 |
| Parallel wave execution | 09 |
| Checkpoint + resume | 10 |
| Artifact lineage tracking | 11 |
| Conditional branching (`IREdge.condition`) | 12 |
| Non-audio / domain-agnostic pipeline | 13 |
| Plugin manifest + versioning | 14 |
| Event-driven execution (file watcher, timer) | 15 |
| Deterministic replay | 16 |
| Partial execution + input injection | 17 |
| Pipeline composition from IR | 18 |
| Capability-aware scheduling | 19 |
| Retry + fault tolerance | 20 |
| Runtime control (pause / resume / cancel) | 21 |

---

## Dataset

Most examples use the **Google Speech Commands v0.02** dataset (Pete Warden, Google, CC BY 4.0).

| File | Size | Contents |
|---|---|---|
| `speech_commands_v0.02.tar.gz` | 2.3 GB | 35 word classes, ~105k clips, 1s, 16kHz |
| `speech_commands_test_set_v0.02.tar.gz` | 108 MB | 12 canonical test classes, ~4800 clips |

### One-time setup

```bash
# Extract datasets
mkdir -p workspace/datasets/raw
tar -xzf speech_commands_v0.02.tar.gz \
    -C workspace/datasets/raw/ --transform 's|^\./|speech_commands_train/|'
tar -xzf speech_commands_test_set_v0.02.tar.gz \
    -C workspace/datasets/raw/ --transform 's|^\./|speech_commands_test/|'

# Copy data into each example's data/ directory
venv/bin/python examples/prepare_real_data.py
```

After setup, each example has its own `data/` directory:

```
examples/01_wake_word/data/
    wake_word/   200 clips  (yes/ from test set)
    background/  200 clips  (no/ + _silence_/ from test set)
    noise/         6 files  (real background noise WAVs)

examples/02_speech_commands/data/
    yes/, no/, up/, down/, go/, stop/   200 clips each

examples/03_environmental_sounds/data/
    dog/, cat/, bird/, happy/, house/   200 clips each

examples/04_speaker_verification/data/
    speaker_001/ … speaker_006/         20 utterances each

examples/05_speech_enhancement/data/
    clean_speech/  200 clips
    noise/           6 noise WAVs
```

---

## Pipeline Format

All pipelines are defined as **IR JSON** (`.graph.json`) — the canonical, versioned, runtime-agnostic format.

```bash
# Validate a pipeline
venv/bin/python -m app.cli.main validate \
    --graph examples/01_wake_word/pipeline.graph.json

# Inspect nodes, edges, and capability summary
venv/bin/python -m app.cli.main inspect \
    --graph examples/01_wake_word/pipeline.graph.json

# Run a pipeline
venv/bin/python -m app.cli.main run \
    --graph examples/01_wake_word/pipeline.graph.json
```

---

## Audio ML Pipeline Examples

These six examples build production-quality audio ML datasets and models, demonstrating the platform's audio processing capabilities end-to-end.

---

### [01 — Wake Word Detection](01_wake_word/)

**Task:** Binary classification — detect "yes" (wake word) vs background speech and silence.

Processes two label classes through gain augmentation, speed perturbation, and Gaussian noise injection at controlled SNR. Both labels are appended to the same output directory. The `data/noise/` directory is present but not used by this example — noise is synthesised (Gaussian) rather than file-based.

```bash
# SDK — processes both labels (wake_word + background)
venv/bin/python examples/01_wake_word/run_sdk.py

# CLI — wake_word label only
bash examples/01_wake_word/run_cli.sh
```

| | |
|---|---|
| **Pipeline** | `dataset_ingest → audio_conditioner → segmenter → augmentation_pipeline(gain+speed_perturb+noise_inject) → audio_exporter` |
| **Input** | 400 clips (200 wake_word + 200 background) |
| **Output** | 4800 samples — 2400 per label, 70/15/15 split |
| **Custom plugin** | None — uses `augmentation_pipeline` with Gaussian noise injection |
| **Model target** | MobileNet-based keyword spotter, TFLite deployment |

---

### [02 — Speech Command Recognition](02_speech_commands/)

**Task:** 6-class spoken command recognition (yes / no / up / down / go / stop).

Uses two `audio_quality_gate` nodes in series — one to reject clips with SNR below 5 dB, a second to enforce a 200ms–1000ms duration window. Runs once per command label, appending to the same output.

```bash
# SDK — all 6 commands
venv/bin/python examples/02_speech_commands/run_sdk.py

# CLI — yes label only
bash examples/02_speech_commands/run_cli.sh
```

| | |
|---|---|
| **Pipeline** | `dataset_ingest → audio_conditioner → segmenter → audio_quality_gate(snr) → audio_quality_gate(duration) → augmentation_pipeline(pitch_shift+time_stretch) → audio_exporter` |
| **Input** | 1200 clips (200 per command) |
| **Output** | ~4800 samples — ~800 per command, 70/15/15 split |
| **Custom plugin** | `audio_quality_gate` — SNR and duration validation |
| **Model target** | DS-CNN / MobileNet for edge deployment |

---

### [03 — Environmental Sound Classification](03_environmental_sounds/)

**Task:** 5-class ambient sound classification at 22050 Hz (ESC-50 style).

Uses `audio_quality_gate` to hard-filter clips outside 500ms–1200ms. Applies two `audio_conditioner` passes — first to resample to 22050 Hz, then for RMS normalisation at −20 dBFS. Runs once per class, appending to the same output.

```bash
# SDK — all 5 classes
venv/bin/python examples/03_environmental_sounds/run_sdk.py

# CLI — dog class only
bash examples/03_environmental_sounds/run_cli.sh
```

| | |
|---|---|
| **Pipeline** | `dataset_ingest → audio_conditioner(22050Hz) → audio_conditioner(rms, −20dBFS) → audio_quality_gate(500ms–1200ms) → augmentation_pipeline(gain+pitch_shift) → audio_exporter` |
| **Input** | 1000 clips (200 per class: dog, cat, bird, happy, house) |
| **Output** | ~4000 samples — ~800 per class, 70/15/15 split |
| **Custom plugin** | `audio_quality_gate` — min/max duration filter |
| **Model target** | VGGish / PANNs with mel-spectrogram input |

---

### [04 — Speaker Verification](04_speaker_verification/)

**Task:** Text-independent speaker verification — "is this the same person speaking?"

Uses the `audio_annotator` node in `auto` mode with duration rules: clips shorter than 500ms are labelled `short_utterance`; clips 500ms or longer are labelled `normal_utterance`. The speaker identity comes from the directory name and is preserved in `AudioSample.label`. Runs once per speaker, appending to the same output.

```bash
# SDK — all 6 speakers
venv/bin/python examples/04_speaker_verification/run_sdk.py

# CLI — speaker_001 only
bash examples/04_speaker_verification/run_cli.sh
```

| | |
|---|---|
| **Pipeline** | `dataset_ingest → audio_conditioner(16kHz) → segmenter(silence) → audio_conditioner(rms, −20dBFS) → audio_annotator(auto: duration rules) → audio_exporter` |
| **Input** | 120 clips (20 utterances × 6 speakers, different words per speaker) |
| **Output** | 120 samples with duration-based annotation metadata, 70/15/15 split |
| **Custom plugin** | `audio_annotator` — rule-based duration annotation |
| **Model target** | ECAPA-TDNN / x-vector with GE2E or ArcFace loss |

---

### [05 — Speech Enhancement](05_speech_enhancement/)

**Task:** Paired clean/degraded speech dataset for training enhancement models.

Runs two passes over the same clean clips. Pass 1 exports them as-is (label `clean_speech`). Pass 2 applies `augmentation_pipeline` with `codec_degrade` (OGG/Vorbis lossy round-trip — MP3 requires pydub+ffmpeg) and `noise_inject` (Gaussian, 10–20 dB SNR), then exports with label `degraded`. A content-diff check at the end verifies the two sets actually differ. `environment_simulator` is not used because `pyroomacoustics` is not installed.

```bash
# SDK
venv/bin/python examples/05_speech_enhancement/run_sdk.py

# CLI
bash examples/05_speech_enhancement/run_cli.sh
```

| | |
|---|---|
| **Pipeline** | Pass 1: `dataset_ingest → audio_conditioner → segmenter → audio_conditioner(compress) → audio_exporter(label=clean_speech)` · Pass 2: same + `augmentation_pipeline(codec_degrade+noise_inject) → audio_exporter(label=degraded, append)` |
| **Input** | 186 clean speech clips |
| **Output** | 372 samples — 186 clean + 186 degraded, 70/15/15 split |
| **Custom plugin** | `augmentation_pipeline` — codec degradation + Gaussian noise injection |
| **Model target** | U-Net / DCCRN / FullSubNet |

---

### [06 — Speech Commands End-to-End Training](06_speech_commands_e2e/)

**Task:** Complete ML pipeline from raw audio to a deployed TFLite model.

Two-phase execution: Phase 1 preprocesses all 6 command labels (identical to Example 02). Phase 2 extracts MFCC features, trains a DS-CNN model, evaluates it, and exports an INT8 TFLite model.

```bash
# Step-by-step CLI (recommended for first run)
bash examples/06_speech_commands_e2e/run_preprocess.sh   # Phase 1: ~45s
bash examples/06_speech_commands_e2e/run_train_ml.sh     # Phase 2: ~8 min
bash examples/06_speech_commands_e2e/run_infer.sh \
    --input examples/02_speech_commands/data/yes         # Inference

# Single SDK script (both phases)
venv/bin/python examples/06_speech_commands_e2e/run_train.py
```

| | |
|---|---|
| **Architecture** | DS-CNN — Depthwise Separable CNN, ~22K parameters |
| **Features** | 40-bin MFCC, 101 frames (~1s at 16kHz) |
| **Test accuracy** | 82–84% |
| **TFLite model** | 44 KB (INT8 quantized) |
| **Inference time** | < 100ms per clip (CPU) |

**Outputs:**
```
output/
├── dataset/speech_commands/v1/   4800 preprocessed WAV files
├── model.keras                   Keras model (385 KB)
├── saved_model/                  TF SavedModel
├── tflite/model.tflite           INT8 TFLite model (44 KB)
├── metrics.json                  Test accuracy + per-class metrics
├── confusion_matrix.png          Confusion matrix heatmap
└── training_curves.png           Loss and accuracy curves
```

---

## Platform Feature Examples

These 15 examples demonstrate the platform's advanced runtime, API, and architectural capabilities. They work with any data — not just audio.

---

### [07 — Agent-Generated Pipeline via MCP](07_mcp_agent_pipeline/)

**The platform as an AI-operable workflow operating system.**

A Python agent communicates with the MCP server and builds, validates, and executes a pipeline entirely through MCP tool calls — no hardcoded graph JSON, no SDK imports. The agent discovers the node vocabulary at runtime and constructs the graph from scratch.

```bash
# Default task: "preprocess audio for keyword spotting"
venv/bin/python examples/07_mcp_agent_pipeline/agent.py

# Different tasks
venv/bin/python examples/07_mcp_agent_pipeline/agent.py \
    --task "augment audio dataset"
venv/bin/python examples/07_mcp_agent_pipeline/agent.py \
    --task "extract features for ml training"

# Verbose — shows full MCP request/response JSON
venv/bin/python examples/07_mcp_agent_pipeline/agent.py --verbose
```

**9-step agent loop:**
```
list_nodes → generate_graph → get_graph_capability_summary →
validate_graph → execute_pipeline → inspect_run (poll) →
inspect_run (logs) → inspect_run (graph snapshot) → report
```

The agent starts its own MCP server subprocess — no separate terminal needed.

---

### [08 — REST API Streaming Execution](08_rest_api_streaming/)

**The REST API as a real-time monitoring interface.**

Submits a pipeline via `POST /api/v1/pipelines/run` and streams the NDJSON execution log in real time, printing each event as it arrives with a live progress bar and per-node timing summary.

```bash
# Start the API server first (separate terminal)
venv/bin/uvicorn app.api.main:app --reload --port 8001

# Basic streaming demo
venv/bin/python examples/08_rest_api_streaming/stream_client.py

# With async run + status polling demo
venv/bin/python examples/08_rest_api_streaming/stream_client.py --async-demo

# Verbose — shows every raw NDJSON line
venv/bin/python examples/08_rest_api_streaming/stream_client.py --verbose
```

**NDJSON event stream:**
```jsonc
{"type": "pipeline_start", "total_nodes": 6, "timestamp": "..."}
{"type": "node_start",  "node_type": "FileInputNode", "node_index": 0, ...}
{"type": "node_end",    "node_type": "FileInputNode", "duration_s": 0.68, "output_count": 200, ...}
// ... more node events ...
{"type": "done", "timestamp": "..."}
```

---

### [09 — Parallel Wave Execution](09_parallel_execution/)

**The platform's parallel DAG executor — 2.7× faster than sequential.**

Builds a fan-out DAG with 4 independent branches (one per label class). The executor automatically groups nodes into parallel waves and runs each wave concurrently.

```bash
# SDK — runs both sequential and parallel, prints timing comparison
venv/bin/python examples/09_parallel_execution/parallel_pipeline.py

# CLI — parallel mode
venv/bin/python -m app.cli.main run \
    --graph examples/09_parallel_execution/pipeline.graph.json --parallel
```

**Wave structure (24 nodes, 6 waves):**
```
Wave 0: dataset_ingest_yes, dataset_ingest_no, dataset_ingest_up, dataset_ingest_down  ← concurrent
Wave 1: audio_conditioner_yes, audio_conditioner_no, audio_conditioner_up, audio_conditioner_down  ← concurrent
Wave 2: segmenter_yes, segmenter_no, segmenter_up, segmenter_down  ← concurrent
...
```

**Results:** Sequential 3.11s → Parallel 1.17s → **2.7× speedup**

---

### [10 — Resumable Pipeline with Checkpointing](10_resumable_pipeline/)

**Checkpoint-based resume — completed nodes are never re-executed.**

Runs a 6-node pipeline with `checkpoint=True`, which writes per-node WAV checkpoints. A background watcher calls `run_mgr.cancel()` after 3 checkpoints appear. The pipeline is then resumed — nodes that already wrote checkpoints are skipped; only the remaining nodes re-execute. The actual number of skipped nodes depends on how many complete before the cancel takes effect; on fast machines the pipeline may finish before the cancel fires, in which case the resume simply re-runs the full graph.

```bash
venv/bin/python examples/10_resumable_pipeline/resumable_pipeline.py
```

**CLI workflow:**
```bash
# Phase 1: run with checkpointing (interrupt with Ctrl+C)
venv/bin/python -m app.cli.main run \
    --graph examples/10_resumable_pipeline/pipeline.graph.json --checkpoint

# Find the interrupted run ID
venv/bin/python -m app.cli.main runs list

# Phase 2: resume
venv/bin/python -m app.cli.main run \
    --graph examples/10_resumable_pipeline/pipeline.graph.json \
    --resume <run_id>
```

---

### [11 — Artifact Lineage Tracking](11_artifact_lineage/)

**Full provenance from dataset version back to original WAV files.**

Runs a preprocessing + feature-extraction pipeline ending at `dataset_versioner` and walks the `ArtifactCollection` returned by `Pipeline.run()`. Demonstrates the lineage tree that traces every artifact back to its origin.

```bash
venv/bin/python examples/11_artifact_lineage/lineage_demo.py
```

**Lineage tree example:**
```
◉ DatasetVersionerNode (dataset_versioner_5)
  └─ DatasetBuilderNode (dataset_builder_4)
    └─ AudioQualityGateNode (audio_quality_gate_3)
      └─ SegmenterNode (segmenter_2)
        └─ AudioConditionerNode (audio_conditioner_1)
          └─ DatasetIngestNode (dataset_ingest_0)
```

**CLI:** `audiobuilder artifacts lineage <artifact_id>`

---

### [12 — Conditional Branching Pipeline](12_conditional_branching/)

**Decision logic inside the graph — not just linear chains.**

Demonstrates `IREdge.condition` — edges that are only traversed when a boolean expression evaluates to `True` against the source node's output. When `False`, the destination node receives `None` and is skipped.

```bash
venv/bin/python examples/12_conditional_branching/conditional_pipeline.py
```

**Graph topology:**
```
dataset_ingest → segmenter ─[len(output) > 0]─► audio_quality_gate → dataset_builder → dataset_versioner (A)
                            └──────────────────► augmentation_pipeline → dataset_builder → dataset_versioner (B)
```

**Condition syntax:** Python boolean expressions — comparisons, `and`/`or`/`not`, `len()`, subscript on `output`.

---

### [13 — CSV Data Processing Pipeline](13_csv_data_processing/)

**The platform is not an audio tool — it's a general-purpose workflow engine.**

Builds a pure data processing pipeline with no audio: reads a CSV file, filters rows by a numeric column, min-max normalizes specified columns, and writes the result. Uses a custom `CSVRow(PortDataType)` data type.

```bash
venv/bin/python examples/13_csv_data_processing/csv_pipeline.py
```

**Pipeline:** `csv_reader → row_filter → column_normalizer → csv_writer`

The node system, DAG executor, caching, and provenance all work identically for any data type. The same pattern extends to text, images, time series, or any domain.

---

### [14 — Plugin Manifest and Versioning](14_plugin_manifest/)

**Full plugin lifecycle — install, use, disable, re-enable, inspect.**

Demonstrates a versioned `plugin.toml` manifest package. The `text-stats` plugin adds a `TextStatsNode` that counts words, characters, and sentences in `DataSample` text fields.

```bash
# Full lifecycle demo
venv/bin/python examples/14_plugin_manifest/manifest_demo.py

# CLI equivalents
venv/bin/python -m app.cli.main plugin install \
    examples/14_plugin_manifest/text_stats_plugin/
venv/bin/python -m app.cli.main plugin list
venv/bin/python -m app.cli.main plugin disable text-stats
venv/bin/python -m app.cli.main plugin enable text-stats
venv/bin/python -m app.cli.main plugin remove text-stats
```

**`plugin.toml` structure:**
```toml
[plugin]
name             = "text-stats"
version          = "1.0.0"
description      = "Text statistics node."
author           = "AudioBuilder Examples"
platform_version = ">=0.0"
entry_points     = ["nodes.py"]
dependencies     = []
```

---

### [15 — Event-Driven Pipeline](15_event_driven_pipeline/)

**The platform as a real-time processing daemon — not just a batch processor.**

Demonstrates `event_driven=True` with two event sources: `TimerSource` (fires every N seconds) and `FileWatcherSource` (triggers on new files in a directory). The pipeline runs indefinitely until `run.cancel()` is called.

```bash
venv/bin/python examples/15_event_driven_pipeline/event_driven_demo.py
```

**Demo 1 — TimerSource:** fires every 2 seconds, runs 3 ticks  
**Demo 2 — FileWatcherSource:** watches a directory, processes 5 WAV files dropped into it

**CLI:** `audiobuilder run --graph pipeline.graph.json --event-driven`

---

### [16 — Deterministic Replay](16_deterministic_replay/)

**Same seed → same output, every time.**

Runs a pipeline, then replays it from the stored `graph.json`. Verifies that the output hash matches exactly. Also shows that a different seed produces different output.

```bash
venv/bin/python examples/16_deterministic_replay/replay_demo.py
```

**Results:**
```
Run 1 (seed=42):  2c9e8cbfe96a486a
Run 2 (replay):   2c9e8cbfe96a486a  ✓ MATCH
Run 3 (seed=99):  b96798f44a01afaa  ✓ DIFFERS (expected)
```

Every run stores its `GraphIR` as `workspace/runs/{run_id}/graph.json`. Replay loads this snapshot and re-executes it with a new `run_id`.

---

### [17 — Partial Execution and Input Injection](17_partial_execution/)

**Re-run only the nodes you changed.**

Demonstrates three execution modes: full pipeline (8 nodes), `exclude_nodes` (skip one node), and `include_nodes` + `input_overrides` (inject pre-computed audio samples and run only the 4 downstream nodes). Speedup varies by machine; the partial run is typically 50–100× faster than the full run because it skips the expensive ingest and conditioning steps.

```bash
venv/bin/python examples/17_partial_execution/partial_demo.py
```

**Results (representative):**
```
Full run (8 nodes):                    ~1.3s
exclude_nodes (7 nodes):               ~0.6s
include_nodes + overrides (4 nodes):   ~0.02s
```

**CLI:**
```bash
venv/bin/python -m app.cli.main run \
    --graph pipeline.graph.json \
    --include-nodes augmentation_pipeline_4,feature_frontend_5,dataset_builder_6,dataset_versioner_7
```

---

### [18 — Pipeline Composition and Reuse](18_pipeline_composition/)

**The IR is a first-class data structure — not just a serialization format.**

Builds two sub-pipelines (preprocessing and augmentation), serializes each to IR JSON, then merges them into a single composed pipeline by combining their nodes and edges programmatically.

```bash
venv/bin/python examples/18_pipeline_composition/composition_demo.py
```

**Composition pattern:**
```python
ir_a = preprocessing_pipeline.to_ir()   # 4 nodes
ir_b = augmentation_pipeline.to_ir()    # 4 nodes

composed = GraphIR(
    nodes=list(ir_a.nodes) + list(ir_b.nodes),
    edges=list(ir_a.edges) + list(ir_b.edges) + [
        IREdge(src_id=ir_a.nodes[-1].id, src_port="output",
               dst_id=ir_b.nodes[0].id,  dst_port="input"),
    ],
    ...
)
```

---

### [19 — Capability-Aware Scheduling](19_capability_scheduling/)

**Machine-readable metadata for hardware-aware scheduling.**

Prints a full capability inventory of all 50 registered nodes, filters by `supports_edge`, `requires_gpu`, and `deterministic`, then builds an edge-optimized inference graph and verifies its capability summary.

```bash
venv/bin/python examples/19_capability_scheduling/capability_demo.py
```

**The 10 capability fields:**

| Field | Meaning |
|---|---|
| `requires_gpu` | Needs GPU acceleration |
| `supports_cpu` | Can run on CPU |
| `supports_edge` | Can run on edge hardware (Raspberry Pi, Jetson, etc.) |
| `deterministic` | Same inputs → same output every time |
| `cacheable` | Output can be cached |
| `streaming_support` | Can process samples one at a time |
| `realtime_support` | Can run in real-time |
| `memory_requirements` | Estimated RAM: `"low"` / `"medium"` / `"high"` |
| `dependency_requirements` | Required pip packages |
| `batch_support` | Can process multiple samples at once |

---

### [20 — Retry and Fault Tolerance](20_retry_fault_tolerance/)

**Production-grade reliability — automatic retry with exponential backoff.**

A `FlakyNode` fails the first 2 attempts and succeeds on the 3rd. `RetryPolicy` handles the retry loop automatically. Total time matches the expected 0.5s + 1.0s backoff.

```bash
venv/bin/python examples/20_retry_fault_tolerance/retry_demo.py
```

**Results:**
```
Attempt 1: ✗ failed (0.5s wait)
Attempt 2: ✗ failed (1.0s wait)
Attempt 3: ✓ succeeded
Total time: 1.50s (matches expected 0.5s + 1.0s backoff)
```

**Backoff formula:** `wait_i = backoff_seconds × (backoff_multiplier ^ i)`

---

### [21 — Runtime Control via REST API and SDK](21_runtime_control_api/)

**Live control over a running pipeline — pause, inspect, resume, cancel.**

Demonstrates all three control interfaces: Python SDK (`RunManager`), REST API (`/api/v1/runs/{id}/pause`), and MCP (`pause_run` tool). All three delegate to the same underlying `RunManager` implementation.

```bash
# SDK-only (no server needed)
venv/bin/python examples/21_runtime_control_api/runtime_control_demo.py --sdk-only

# Full demo including REST API
venv/bin/uvicorn app.api.main:app --reload --port 8001
venv/bin/python examples/21_runtime_control_api/runtime_control_demo.py
```

**Control signals are checked between nodes** — execution is never interrupted mid-node, guaranteeing consistent outputs.

---

## Custom Plugins

All examples use plugin nodes from `PluginPackage/` via `PluginManager`. All node types (`audio_quality_gate`, `audio_conditioner`, `segmenter`, `audio_annotator`, `augmentation_pipeline`, and others) are registered in `PluginPackage/Audio/` and loaded at runtime.

### Using a plugin (examples 06 and 14)

```bash
# Set GRAPHYN_PLUGINS_DIR before running
GRAPHYN_PLUGINS_DIR="examples/06_speech_commands_e2e/plugins" \
    venv/bin/python -m app.cli.main run \
    --graph examples/06_speech_commands_e2e/pipeline_train_ml.graph.json
```

```python
import os
os.environ["GRAPHYN_PLUGINS_DIR"] = "examples/06_speech_commands_e2e/plugins"
from app.core.sdk import Pipeline, PipelineNode  # AutoDiscovery runs here
```

### Built-in nodes used by examples 02–05

These nodes are part of the core platform — no plugin setup required:

| Example | Node | Category | What it does |
|---|---|---|---|
| 02 | `audio_quality_gate` | Validation | Rejects clips with SNR < 5 dB and duration outside 200ms–1000ms |
| 03 | `audio_quality_gate` | Filtering | Hard filter by min/max duration (500ms–1200ms) |
| 04 | `audio_annotator` | Annotation | Assigns `short_utterance` / `normal_utterance` label based on clip duration |
| 05 | `augmentation_pipeline` | Augmentation | Applies codec degradation (OGG lossy round-trip) + Gaussian noise injection |

### Plugin nodes (examples 06 and 14)

These nodes are loaded from the example's `plugins/` directory at runtime:

| Example | Plugin nodes | What they do |
|---|---|---|
| 14 | `text_stats` | Counts words, characters, and sentences in `DataSample` text fields |

---

## Output Format

All audio examples produce a standard dataset directory:

```
output/{project}/{version}/
├── train/{label}/{hash_id}.wav
├── val/{label}/{hash_id}.wav
├── test/{label}/{hash_id}.wav
├── labels.csv          # id, path, label, split
└── metadata.json       # full sample metadata including augmentation fields
```

---

## Verified Results

All examples have been tested with real Google Speech Commands v0.02 data.

| Example | Input | Output | Time |
|---|---|---|---|
| 01 Wake Word | 400 clips (2 labels) | 4800 samples | ~25s |
| 02 Speech Commands | 1200 clips (6 labels) | 4800 samples | ~45s |
| 03 Environmental Sounds | 1000 clips (5 classes) | 4000 samples | ~40s |
| 04 Speaker Verification | 120 clips (6 speakers) | 120 samples + metadata | ~5s |
| 05 Speech Enhancement | 186 clips | 372 paired samples | ~15s |
| 06 E2E Training | 1200 clips → 4800 features | 82–84% accuracy, 44 KB TFLite | ~8 min |
| 07 MCP Agent | — | Pipeline built + run via MCP | ~3s |
| 08 REST Streaming | 200 clips | NDJSON stream + timing summary | ~1s |
| 09 Parallel | 800 clips (4 labels) | 4 × 800 samples | 1.2s (**2.7× speedup**) |
| 10 Resumable | 200 clips | Skips checkpointed nodes on resume | varies |
| 12 Conditional | 200 clips | Branch A or B based on condition | ~2s |
| 13 CSV | 100 rows | 62 filtered + normalized rows | <1s |
| 16 Replay | 200 clips | Identical output hash confirmed | ~2s |
| 17 Partial | 200 clips | 4/8 nodes executed | ~0.02s partial run |
| 18 Composition | 200 clips | 8-node composed pipeline | ~3s |
| 20 Retry | — | 3 attempts, 1.5s total backoff | 1.5s |
