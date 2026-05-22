# Example 09 — Parallel Wave Execution

Demonstrates the platform's **parallel DAG executor** — nodes in the same execution wave run concurrently via `ThreadPoolExecutor`, delivering measurable speedup over sequential execution.

---

## What This Demonstrates

- `pipeline.run(parallel=True)` — enable parallel wave execution
- `execution_waves` — nodes automatically grouped into independent waves
- `wave_start` / `wave_end` log events — wave lifecycle visibility
- `ParallelExecutor` with `asyncio.gather` + `ThreadPoolExecutor`
- Wall-clock speedup measurement vs sequential baseline

---

## Pipeline Shape

A fan-out DAG with 4 independent branches (one per label class):

```
dataset_ingest(yes)  ─┬─ audio_conditioner → segmenter → augmentation_pipeline → audio_exporter(yes)
dataset_ingest(no)   ─┼─ audio_conditioner → segmenter → augmentation_pipeline → audio_exporter(no)
dataset_ingest(up)   ─┼─ audio_conditioner → segmenter → augmentation_pipeline → audio_exporter(up)
dataset_ingest(down) ─┘─ audio_conditioner → segmenter → augmentation_pipeline → audio_exporter(down)
```

The executor automatically detects that all 4 branches are independent and groups them into parallel waves:

| Wave | Nodes | Runs concurrently? |
|---|---|---|
| 0 | 4 × `dataset_ingest` | ✅ Yes |
| 1 | 4 × `audio_conditioner` | ✅ Yes |
| 2 | 4 × `segmenter` | ✅ Yes |
| 3 | 4 × `augmentation_pipeline` | ✅ Yes |
| 4 | 4 × `audio_exporter` | ✅ Yes |

---

## How to Run

```bash
# SDK — runs both sequential and parallel, prints timing comparison
venv/bin/python examples/09_parallel_execution/parallel_pipeline.py

# CLI — parallel mode
venv/bin/python -m app.cli.main run \
    --graph examples/09_parallel_execution/pipeline.graph.json \
    --parallel

# CLI — sequential mode (for comparison)
venv/bin/python -m app.cli.main run \
    --graph examples/09_parallel_execution/pipeline.graph.json
```

---

## Results

```
Sequential:  5.09s  (20 nodes, one at a time)
Parallel:    2.02s  (20 nodes, 4 per wave)
Speedup:     2.5×
```

The speedup is limited by I/O (file reading/writing) and Python's GIL for CPU-bound operations. For I/O-bound workloads the speedup approaches the number of independent branches.

---

## How It Works

The `PipelineGraph` computes `execution_waves` at build time using a level-based BFS:

- Wave 0 = all source nodes (no predecessors)
- Wave N = nodes whose predecessors all belong to waves 0..N-1

`ParallelExecutor` runs each wave with `asyncio.gather`, submitting each node to a `ThreadPoolExecutor`. Nodes in the same wave have no data dependency on each other and can safely run concurrently.

```python
# Enable parallel execution
result = pipeline.run(parallel=True)

# Control thread pool size
result = pipeline.run(parallel=True, max_workers=4)

# Inspect waves before running
from app.core.pipeline import PipelineGraph, _ir_to_pipeline_config
cfg   = _ir_to_pipeline_config(pipeline.to_ir())
graph = PipelineGraph(cfg)
for i, wave in enumerate(graph.execution_waves):
    print(f"Wave {i}: {wave}")
```
