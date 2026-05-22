# Example 17 — Partial Execution and Input Injection

Demonstrates `include_nodes`, `exclude_nodes`, and `input_overrides` — features that let you execute only a subset of a pipeline's nodes, optionally injecting pre-computed data at any node's input port.

---

## What This Demonstrates

- `pipeline.run(include_nodes=[...])` — execute only specified nodes
- `pipeline.run(exclude_nodes=[...])` — skip specified nodes
- `pipeline.run(input_overrides={...})` — inject data at a node's input port
- How partial execution interacts with the cache and checkpoint system
- `audiobuilder run --graph ... --include-nodes id1,id2` — CLI usage
- `audiobuilder run --graph ... --exclude-nodes id1` — CLI usage

---

## How to Run

```bash
# Prepare data (if not already done)
venv/bin/python examples/prepare_real_data.py

venv/bin/python examples/17_partial_execution/partial_demo.py
```

---

## Expected Output

```
Run 1 — Full pipeline (baseline)
  ✓ Full run: 5.54s  run_id=7ad37bce

Run 2 — exclude_nodes=["augmentation_pipeline_4"]
  ✓ Excluded augmentation_pipeline: 2.44s  run_id=18eaa947

Run 3 — include_nodes + input_overrides
  Pre-computed samples: 10 AudioSample objects
  ✓ Partial run (4/8 nodes): 0.22s  run_id=4c8730d4
  Speedup vs full: 25.2×

Summary
  Full run (8 nodes):              5.54s
  exclude_nodes (7 nodes):         2.44s
  include_nodes + overrides (4):   0.22s
```

---

## SDK Usage

```python
from app.core.sdk import Pipeline, PipelineNode

pipeline = Pipeline([
    PipelineNode("dataset_ingest",        {"path": "data/yes", "recursive": False, "source_type": "filesystem"}),
    PipelineNode("audio_conditioner",     {"target_sample_rate": 16000}),
    PipelineNode("segmenter",             {"silence_threshold_db": 40.0, "mode": "silence"}),
    PipelineNode("audio_quality_gate",    {"min_snr_db": -60.0}),
    PipelineNode("augmentation_pipeline", {"augmentations": [{"type": "gain", "gain_db": [-3.0, 3.0], "copies_per_sample": 1}]}),
    PipelineNode("feature_frontend",      {"feature_type": "mfcc", "n_mfcc": 40}),
    PipelineNode("dataset_builder",       {"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}, "fixed_length": 101}),
    PipelineNode("dataset_versioner",     {"output_dir": "output/", "version_tag": "v1"}),
], seed=42)

# Run only specific nodes (IDs are node_type + index, e.g. augmentation_pipeline_4)
result = pipeline.run(
    include_nodes=["augmentation_pipeline_4", "feature_frontend_5",
                   "dataset_builder_6", "dataset_versioner_7"]
)

# Skip specific nodes
result = pipeline.run(exclude_nodes=["augmentation_pipeline_4"])

# Inject pre-computed data at a node's input port
from app.models.audio_sample import AudioSample
import numpy as np

pre_computed = [
    AudioSample(path=f"/data/{i}.wav", sample_rate=16000,
                data=np.zeros(16000, dtype=np.float32), label="yes")
    for i in range(10)
]

result = pipeline.run(
    include_nodes=["augmentation_pipeline_4", "feature_frontend_5",
                   "dataset_builder_6", "dataset_versioner_7"],
    input_overrides={"augmentation_pipeline_4": {"input": pre_computed}},
)
```

---

## CLI Usage

```bash
# Run only specific nodes
venv/bin/python -m app.cli.main run \
    --graph pipeline.graph.json \
    --include-nodes augmentation_pipeline_4,feature_frontend_5,dataset_builder_6,dataset_versioner_7

# Skip specific nodes
venv/bin/python -m app.cli.main run \
    --graph pipeline.graph.json \
    --exclude-nodes augmentation_pipeline_4
```

---

## Rules

- `include_nodes` and `exclude_nodes` are **mutually exclusive** — use one or the other
- `input_overrides` injects data at a specific node's input port, bypassing upstream nodes
- Boundary nodes (first included node) source inputs from `input_overrides` → latest checkpoint → `None`
- Node IDs are auto-generated as `{node_type}_{index}` (e.g. `augmentation_pipeline_4`, `dataset_builder_6`)

---

## Use Cases

- **Fast iteration**: change a late-stage node's config and re-run only from that node forward
- **Debugging**: inject known-good data at a specific point to isolate a problem
- **Testing**: run only the export node with synthetic data to verify output format
- **Cost reduction**: skip expensive augmentation nodes during quick validation runs
