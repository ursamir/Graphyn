# Example 16 — Deterministic Replay

Demonstrates that pipelines with a fixed `seed` produce identical outputs on replay, and shows the replay mechanism via the stored `graph.json`.

---

## What This Demonstrates

- `graph.json` stored per run in `workspace/runs/{run_id}/`
- Replay — loads `graph.json` and re-executes with a new `run_id`
- `seed` field in `IRMetadata` — controls all random operations
- `deterministic=True` capability field — which nodes guarantee identical output
- `audiobuilder artifacts replay <run_id>` — CLI replay
- `POST /api/v1/artifacts/{id}/replay` — REST API replay

---

## How to Run

```bash
# Prepare data (if not already done)
venv/bin/python examples/prepare_real_data.py

venv/bin/python examples/16_deterministic_replay/replay_demo.py
```

---

## Expected Output

```
Run 1 — Original (seed=42)
  ✓ run_id: 0b8f6f14
    output hash: 2c9e8cbfe96a486a
    graph.json stored: 6 nodes, seed=42

Run 2 — Replay from stored graph.json
  Loading graph from workspace/runs/0b8f6f14/graph.json
  ✓ new run_id: 8fa119de
    output hash: 2c9e8cbfe96a486a

Run 3 — Different seed (seed=99) — should differ
  ✓ run_id: 915a36f9
    output hash: b96798f44a01afaa

Comparison
  Run 1 (seed=42):  2c9e8cbfe96a486a
  Run 2 (replay):   2c9e8cbfe96a486a  ✓ MATCH
  Run 3 (seed=99):  b96798f44a01afaa  ✓ DIFFERS (expected)

  ✓ Deterministic replay confirmed — same seed → same output
```

---

## How Replay Works

Every pipeline run stores its `GraphIR` as `workspace/runs/{run_id}/graph.json`. This snapshot includes the exact node configurations and seed used. Replay loads this snapshot and re-executes it:

```python
import json
from app.core.ir.loader import load_ir
from app.core.pipeline import run_pipeline_ir
from app.core.run_manager import RunManager

# Load the stored graph
with open(f"workspace/runs/{run_id}/graph.json") as f:
    graph_dict = json.load(f)

ir = load_ir(graph_dict)
new_run_mgr = RunManager()
run_pipeline_ir(ir, run_manager=new_run_mgr)
print(f"Replay run_id: {new_run_mgr.run_id}")
```

---

## Determinism and the Seed

The `seed` field in `IRMetadata` is passed to every node at construction time. Nodes that use random operations (augmentation, pitch shift, noise mixing) use this seed to initialize their RNG, ensuring reproducible output.

Nodes with `deterministic=True` in their capability metadata guarantee identical output for identical inputs and config. Nodes with `deterministic=False` (e.g. `augmentation_pipeline`) are reproducible only when the same seed is used **and** the underlying library's RNG behaviour is consistent across runs.

In practice, the demo confirms replay by hashing the `manifest.csv` written by `dataset_versioner`. If the hashes match, the pipeline is deterministic end-to-end for the given seed.

---

## CLI Usage

```bash
# Replay a run
audiobuilder artifacts replay <run_id>

# List recent runs to find a run_id
audiobuilder runs list

# REST API
curl -X POST http://localhost:8001/api/v1/artifacts/<artifact_id>/replay
```
