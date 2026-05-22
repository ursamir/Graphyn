# Example 18 — Pipeline Composition and Reuse

Demonstrates the IR as a **composable, programmable graph format** — not just a serialization format, but a first-class data structure that can be manipulated, merged, and reused programmatically.

---

## What This Demonstrates

- `pipeline.to_ir()` — get the backing `GraphIR` object
- `pipeline.to_json(path)` — serialize to `.graph.json`
- `Pipeline.from_json(path)` — load and preserve explicit edges
- Programmatic IR manipulation: merge nodes + edges from two graphs
- `load_ir(dict)` / `dump_ir(graph)` — IR serialization primitives
- `IRNode`, `IREdge`, `IRMetadata` — IR model construction

---

## How to Run

```bash
# Prepare data (if not already done)
venv/bin/python examples/prepare_real_data.py

venv/bin/python examples/18_pipeline_composition/composition_demo.py
```

---

## Expected Output

```
Step 1 — Build two sub-pipelines
  Sub-pipeline A (preprocessing): 4 nodes
    dataset_ingest_0 (dataset_ingest)
    audio_conditioner_1 (audio_conditioner)
    segmenter_2 (segmenter)
    audio_quality_gate_3 (audio_quality_gate)
  Sub-pipeline B (augmentation): 4 nodes
    augmentation_pipeline_0 (augmentation_pipeline)
    feature_frontend_1 (feature_frontend)
    dataset_builder_2 (dataset_builder)
    dataset_versioner_3 (dataset_versioner)

Step 2 — Serialize sub-pipelines to IR JSON
  ✓ preprocessing.graph.json
  ✓ augmentation.graph.json

Step 3 — Load from JSON (verify round-trip)
  ✓ Loaded A: 4 nodes, edges preserved: 3
  ✓ Loaded B: 4 nodes, edges preserved: 3

Step 4 — Compose into single pipeline
  ✓ Composed: 8 nodes, 7 edges
  Connecting edge: audio_quality_gate_3.output → augmentation_pipeline_0.input
  Saved: .../composed.graph.json

Step 5 — Run composed pipeline
  ✓ Composed pipeline completed
    run_id: d6556861
```

---

## Composition Pattern

```python
from app.core.ir.loader import CURRENT_IR_VERSION, dump_ir_to_file
from app.core.ir.models import GraphIR, IREdge, IRMetadata
from app.core.sdk import Pipeline

# Build sub-pipelines
pipe_a = Pipeline([PipelineNode("dataset_ingest", {...}), PipelineNode("audio_conditioner", {...})])
pipe_b = Pipeline([PipelineNode("augmentation_pipeline", {...}), PipelineNode("dataset_versioner", {...})])

# Get their IR objects
ir_a = pipe_a.to_ir()
ir_b = pipe_b.to_ir()

# Merge nodes and edges
all_nodes = list(ir_a.nodes) + list(ir_b.nodes)
all_edges = list(ir_a.edges) + list(ir_b.edges)

# Add a connecting edge between the two sub-pipelines
all_edges.append(IREdge(
    src_id=ir_a.nodes[-1].id, src_port="output",
    dst_id=ir_b.nodes[0].id,  dst_port="input",
))

# Build the composed graph
composed = GraphIR(
    schema_version=CURRENT_IR_VERSION,
    metadata=IRMetadata(name="composed", seed=42),
    nodes=all_nodes,
    edges=all_edges,
)

# Save and run
dump_ir_to_file(composed, "composed.graph.json")
```

---

## Round-Trip Serialization

`Pipeline.from_json()` preserves explicit edges from the IR — critical for multi-port nodes:

```python
# Save
pipeline.to_json("my_pipeline.graph.json")

# Load — edges are preserved exactly as stored
loaded = Pipeline.from_json("my_pipeline.graph.json")
assert len(loaded.to_ir().edges) == len(pipeline.to_ir().edges)
```

---

## Use Cases

- **Modular pipelines**: build reusable preprocessing, augmentation, and export sub-pipelines
- **Pipeline libraries**: serialize common patterns as `.graph.json` files and compose them
- **Dynamic graph construction**: build graphs programmatically based on runtime conditions
- **Graph versioning**: serialize each version of a pipeline for reproducibility
