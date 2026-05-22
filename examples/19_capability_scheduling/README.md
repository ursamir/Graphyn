# Example 19 — Capability-Aware Scheduling

Demonstrates the platform's machine-readable capability metadata system — the foundation for hardware-aware scheduling and edge deployment planning.

---

## What This Demonstrates

- Full capability inventory of all registered nodes
- `list_nodes(capability_filter={"supports_edge": True})` via MCP
- `get_graph_capability_summary` — aggregate capability analysis for a graph
- `IRCapabilityMetadata` fields: `supports_edge`, `memory_requirements`, `batch_support`, `deterministic`
- How capability metadata enables hardware-aware scheduling
- Building an edge-optimized inference graph using only edge-compatible nodes

---

## How to Run

```bash
venv/bin/python examples/19_capability_scheduling/capability_demo.py
```

---

## Expected Output

```
Step 1 — Full capability inventory
  32 nodes registered. Capability breakdown:

  node_type                 cat                 gpu  edge  det cache stream batch mem
  ─────────────────────────────────────────────────────────────────────────────────
  augmentation_pipeline     Augmentation        ✗    ✓     ✗   ✗     ✗      ✗    —
  feature_frontend          Features            ✗    ✓     ✓   ✓     ✗      ✗    —
  trainer                   ML                  ✗    ✗     ✗   ✗     ✗      ✓    high
  edge_optimizer            Export              ✗    ✓     ✓   ✓     ✗      ✗    medium
  ...

Step 2 — Filter: supports_edge=True
  13 edge-compatible nodes:
    ✓ audio_annotator           [Preprocessing]
    ✓ audio_classifier          [Inference]
    ✓ audio_conditioner         [Preprocessing]
    ✓ audio_event_detector      [Detection]
    ✓ audio_quality_gate        [Validation]
    ✓ augmentation_pipeline     [Augmentation]
    ✓ deployment_packager       [ML]
    ✓ edge_optimizer            [Export]  mem=medium
    ✓ feature_frontend          [Features]
    ✓ realtime_inference        [Inference]
    ✓ segmenter                 [Processing]
    ✓ stream_ingest             [Input]
    ✓ stream_processor          [Streaming]

Step 4 — Filter: deterministic=False (random augmentation nodes)
  8 non-deterministic nodes:
    ~ audio_generator, augmentation_pipeline, speaker_separator,
      speech_enhancer, speech_synthesizer, stream_ingest, trainer, voice_converter

Step 6 — Compute graph capability summary
  ✓ all_support_edge: True
  ✓ all_support_cpu: True
  ✓ all_deterministic: False  (stream_ingest is non-deterministic)
  ✗ any_requires_gpu: False
  ✗ any_batch_support: False

  ✓ This graph is EDGE-DEPLOYABLE — all nodes support edge hardware
  ✓ No GPU required — can run on CPU-only edge devices
```

---

## The 10 Capability Fields

Every node declares these fields in its `NodeMetadata`:

| Field | Type | Meaning |
|---|---|---|
| `requires_gpu` | bool | Node requires GPU acceleration |
| `supports_cpu` | bool | Node can run on CPU |
| `supports_edge` | bool | Node can run on edge hardware (Raspberry Pi, Jetson, etc.) |
| `deterministic` | bool | Same inputs + config → same output every time |
| `cacheable` | bool | Output can be cached for re-use |
| `streaming_support` | bool | Node can process samples one at a time |
| `realtime_support` | bool | Node can run in real-time |
| `memory_requirements` | str | Estimated RAM footprint: `"low"`, `"medium"`, `"high"` |
| `dependency_requirements` | list | Required pip packages |
| `batch_support` | bool | Node can process multiple samples at once |

---

## Graph Capability Summary

The `get_graph_capability_summary` MCP tool aggregates capability metadata across all nodes in a graph:

```python
from app.mcp.handlers.graph import get_graph_capability_summary_handler
from app.core.ir.loader import dump_ir

summary = get_graph_capability_summary_handler({"graph": dump_ir(graph)})
# Returns:
# {
#   "any_requires_gpu": False,
#   "all_support_cpu": True,
#   "all_support_edge": False,
#   "all_deterministic": True,
#   "any_batch_support": True,
# }
```

---

## Filtering Nodes by Capability

```python
from app.core.registry_runtime import get_registry

registry = get_registry()

# Find all edge-compatible nodes
edge_nodes = [m for m in registry.list_nodes() if m.supports_edge]

# Find all non-deterministic nodes (augmentation)
random_nodes = [m for m in registry.list_nodes() if not m.deterministic]

# Find all GPU-required nodes
gpu_nodes = [m for m in registry.list_nodes() if m.requires_gpu]
```

---

## Phase 6 Connection

The `supports_edge` capability field is the hook that Phase 6 (Edge AI Expansion) will use to filter and schedule nodes for deployment to edge hardware targets:

- Raspberry Pi, NVIDIA Jetson, Coral TPU
- TFLite, ONNX Runtime, TensorRT
- STM32 AI, ESP32, Android NNAPI

The edge-optimized graph saved by this example (`edge_inference.graph.json`) is ready for Phase 6 deployment packaging.
