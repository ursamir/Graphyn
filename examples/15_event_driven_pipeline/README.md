# Example 15 — Event-Driven Pipeline

Demonstrates `event_driven=True` — a pipeline that runs indefinitely, triggering on events from `FileWatcherSource` or `TimerSource` rather than executing once and stopping.

---

## What This Demonstrates

- `event_driven=True` on `Pipeline.run()` — indefinite execution
- `IRNode.event_trigger` — binding a node to an event source
- `FileWatcherSource` — watches a directory for new `.wav` files
- `TimerSource` — fires at a configurable interval
- `QueueSource` — programmatic event injection
- `run.cancel()` — graceful shutdown after the current node completes
- `audiobuilder run --graph ... --event-driven` — CLI usage

---

## How to Run

```bash
# Prepare data (if not already done)
venv/bin/python examples/prepare_real_data.py

venv/bin/python examples/15_event_driven_pipeline/event_driven_demo.py
```

The demo runs two sub-demos:
1. **TimerSource** — fires every 2 seconds, runs 3 ticks then stops
2. **FileWatcherSource** — watches a directory, processes 5 WAV files dropped into it

---

## Expected Output

```
Demo 1 — TimerSource (fires every 2s, runs 6s)
  tick #1  2026-05-18T07:11:36+00:00
  tick #2  2026-05-18T07:11:38+00:00
  tick #3  2026-05-18T07:11:40+00:00
  ✓ TimerSource fired 3 times

Demo 2 — FileWatcherSource (watches directory for new WAV files)
  Watch dir: .../watch_inbox
  Dropping files into watch dir...
  → dropped clip_00.wav
  → dropped clip_01.wav
  ...
  ✓ Pipeline cancelled gracefully
    run_id: 540d4035
  ✓ node_end events: 24  (4 nodes × 6 triggers: 1 initial + 5 file drops)
```

---

## Event Trigger in Graph JSON

Bind a node to an event source via `event_trigger` in the graph JSON:

```json
{
  "id": "dataset_ingest_0",
  "node_type": "dataset_ingest",
  "config": {"path": "/watch/dir", "recursive": false, "source_type": "filesystem"},
  "event_trigger": {
    "source_type": "file_watcher",
    "source_config": {
      "path": "/watch/dir",
      "pattern": "*.wav"
    }
  }
}
```

Available source types:

| Source | Config keys | Yields |
|---|---|---|
| `file_watcher` | `path`, `pattern` | `{"path": "...", "event": "created"\|"modified"}` |
| `timer` | `interval_s` | `{"tick": N, "timestamp": "..."}` |
| `queue` | *(queue passed directly)* | whatever dict is put in the queue |

---

## SDK Usage

```python
import threading
from app.core.sdk import Pipeline, PipelineNode
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode
from app.core.ir.loader import CURRENT_IR_VERSION
from app.core.run_manager import RunManager

# Build a pipeline with an event-triggered node
graph = GraphIR(
    schema_version=CURRENT_IR_VERSION,
    metadata=IRMetadata(name="event-driven", seed=42),
    nodes=[
        IRNode(
            id="dataset_ingest_0",
            node_type="dataset_ingest",
            config={"path": "/watch/dir", "recursive": False, "source_type": "filesystem"},
            event_trigger={
                "source_type": "file_watcher",
                "source_config": {"path": "/watch/dir", "pattern": "*.wav"},
            },
        ),
        IRNode(id="audio_conditioner_1", node_type="audio_conditioner",
               config={"target_sample_rate": 16000}),
    ],
    edges=[
        IREdge(src_id="dataset_ingest_0", src_port="output",
               dst_id="audio_conditioner_1", dst_port="input"),
    ],
)

# Pipeline.run() supports event_driven=True directly
from app.core.pipeline import run_pipeline_ir

run_mgr = RunManager()

def _run():
    run_pipeline_ir(graph, event_driven=True, run_manager=run_mgr)

thread = threading.Thread(target=_run, daemon=True)
thread.start()

# ... do other work ...

# Graceful shutdown
run_mgr.cancel()
thread.join(timeout=10)
```

---

## CLI Usage

```bash
# Run a pipeline in event-driven mode
venv/bin/python -m app.cli.main run \
    --graph examples/15_event_driven_pipeline/pipeline.graph.json \
    --event-driven
```

The pipeline runs indefinitely until interrupted with `Ctrl+C`.
