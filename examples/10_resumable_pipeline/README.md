# Example 10 — Resumable Pipeline with Checkpointing

Demonstrates checkpoint-based resumability — a pipeline that writes per-node checkpoints and can be resumed from the last completed node without re-processing earlier stages.

---

## What This Demonstrates

- `pipeline.run_with_manager(checkpoint=True)` — write per-node WAV checkpoints
- `pipeline.run_with_manager(resume_run_id=run_id)` — resume from prior run
- `resume_state.json` — tracks completed nodes and graph hash
- `node_skip(reason="resumed_from_checkpoint")` — skipped node log events
- `run.cancel()` — graceful cancellation between nodes
- `audiobuilder runs list` — find interrupted run IDs
- `audiobuilder run --graph ... --resume <run_id>` — CLI resume

---

## How It Works

**Phase 1 — Run with checkpointing:**

The pipeline runs all 6 nodes to completion with `checkpoint=True`. Each completed node writes its output to:
```
workspace/runs/{run_id}/checkpoints/node_{id}/
    *.wav           — output audio files
    manifest.json   — sample metadata
```

And `resume_state.json` records which nodes completed:
```json
{
  "graph_hash": "cec29974...",
  "completed_nodes": ["dataset_ingest_0", "audio_conditioner_1", "segmenter_2", ...]
}
```

To simulate a crash, the demo then removes the last 2 checkpoints (`augmentation_pipeline_4`, `audio_exporter_5`) and patches `resume_state.json` to reflect only 4 completed nodes — as if the run had been interrupted after node 3.

**Phase 2 — Resume:**

Skipped nodes load their outputs from checkpoints. Only the 2 remaining nodes execute — saving significant time on long pipelines.

---

## How to Run

```bash
# SDK — runs both phases automatically
venv/bin/python examples/10_resumable_pipeline/resumable_pipeline.py

# CLI — Phase 1 (run with checkpointing, interrupt with Ctrl+C)
venv/bin/python -m app.cli.main run \
    --graph examples/10_resumable_pipeline/pipeline.graph.json \
    --checkpoint

# Find the interrupted run ID
venv/bin/python -m app.cli.main runs list

# CLI — Phase 2 (resume)
venv/bin/python -m app.cli.main run \
    --graph examples/10_resumable_pipeline/pipeline.graph.json \
    --resume <run_id>
```

---

## Results

```
Phase 1 (full run, 6 nodes):   7.75s
Phase 2 (resume, 2 nodes):     5.00s  (4 skipped from checkpoints)
Time saved:                    ~35%
```

---

## SDK Usage

```python
from app.core.sdk import Pipeline, PipelineNode

pipeline = Pipeline([...], seed=42)

# Phase 1: run with checkpointing
result, run_mgr = pipeline.run_with_manager(checkpoint=True)
run_id = run_mgr.run_id

# Phase 2: resume (skips completed nodes)
result2, run_mgr2 = pipeline.run_with_manager(resume_run_id=run_id)
```

---

## Use Cases

- Long ML preprocessing jobs where a crash mid-run would otherwise require starting over
- Iterative development: change a late-stage node's config and re-run only from that node forward
- Distributed pipelines where individual stages may fail independently
