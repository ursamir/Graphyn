# Example 12 — Conditional Branching Pipeline

Demonstrates `IREdge.condition` — edges that are only traversed when a boolean expression evaluates to `True` against the source node's output. This enables decision logic inside the graph itself, not just linear chains.

---

## What This Demonstrates

- `IREdge.condition` field in the graph JSON
- `evaluate_condition()` — restricted AST evaluator (safe subset of Python)
- `node_skip(reason="condition_false")` — skipped node log events
- Branching DAG topology (one source, two sinks)
- How to write conditional edges programmatically

---

## Pipeline Shape

```
dataset_ingest → segmenter ─[condition]─► audio_quality_gate → feature_frontend → dataset_builder → dataset_versioner (branch A)
                            └────────────► augmentation_pipeline → feature_frontend → dataset_builder → dataset_versioner (branch B)
```

The condition is evaluated against `segmenter`'s output dict at runtime:
- If `True`: `audio_quality_gate` runs (branch A executes)
- If `False`: `audio_quality_gate` is skipped, receives `None` (branch A skipped)

Branch B (`augmentation_pipeline`) always runs — it has no condition on its edge.

---

## How to Run

```bash
# Prepare data (if not already done)
venv/bin/python examples/prepare_real_data.py

venv/bin/python examples/12_conditional_branching/conditional_pipeline.py
```

---

## Condition Expression Syntax

Conditions are Python boolean expressions evaluated against the source node's `output` dict. Only a safe subset is allowed:

| Allowed | Example |
|---|---|
| Comparisons | `len(output) > 0` |
| Boolean operators | `len(output) > 0 and len(output) < 1000` |
| Subscript access | `output["output"][0].label == "yes"` |
| `len()` function | `len(output["output"]) > 10` |
| Integer/string/bool literals | `True`, `42`, `"yes"` |

| Disallowed |
|---|
| Imports |
| Arbitrary function calls |
| Attribute access on non-`output` names |
| Assignments, comprehensions, lambdas |

---

## Graph JSON Format

Conditional edges are expressed in the `.graph.json` file:

```json
{
  "edges": [
    {
      "src_id": "segmenter_1",
      "src_port": "output",
      "dst_id": "audio_quality_gate_2",
      "dst_port": "input",
      "condition": "len(output) > 0"
    },
    {
      "src_id": "segmenter_1",
      "src_port": "output",
      "dst_id": "augmentation_pipeline_3",
      "dst_port": "input"
    }
  ]
}
```

---

## SDK Usage

```python
from app.core.ir.models import GraphIR, IREdge, IRNode, IRMetadata
from app.core.ir.loader import CURRENT_IR_VERSION

graph = GraphIR(
    schema_version=CURRENT_IR_VERSION,
    metadata=IRMetadata(name="conditional", seed=42),
    nodes=[...],
    edges=[
        # Unconditional edge
        IREdge(src_id="a", src_port="output", dst_id="b", dst_port="input"),
        # Conditional edge — only traversed when condition is True
        IREdge(src_id="a", src_port="output", dst_id="c", dst_port="input",
               condition="len(output) > 100"),
    ],
)
```

---

## Inspect the Graph

```bash
venv/bin/python -m app.cli.main inspect \
    --graph examples/12_conditional_branching/pipeline.graph.json
```

The inspect output shows conditional edges with their expressions:
```
segmenter_1.output → audio_quality_gate_2.input  [if: len(output) > 0]
segmenter_1.output → augmentation_pipeline_3.input
```
