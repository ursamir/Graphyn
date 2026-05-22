# req-04 — Conditional Branching

## Overview

Conditional edges allow data to flow only when a boolean expression evaluates to `True` against the source node's output, enabling dynamic routing within a single graph definition.

---

## Current State

`IREdge` has no condition field. All edges always transmit data. The IR schema version is `"1.0"`.

---

## Design

### IR Schema Extension

`app/core/ir/models.py` — `IREdge` gains one optional field:

```python
class IREdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    src_id: str
    src_port: str
    dst_id: str
    dst_port: str
    condition: str | None = None  # NEW — Phase 3
```

Schema version bumped to `"1.1"` in `app/core/ir/loader.py`:

```python
SUPPORTED_MAJOR = 1
SUPPORTED_MINOR_MAX = 1   # was 0
```

The loader accepts `"1.0"` and `"1.1"`. A `"1.0"` document is treated as `"1.1"` with `condition=None` on all edges.

### Condition Evaluation

A restricted evaluator in `app/core/conditions.py`:

```python
import ast
import operator

_SAFE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
    ast.Not: operator.not_,
}

def evaluate_condition(expression: str, output: dict) -> bool:
    """Evaluate a condition expression against a node's output dict.

    The expression has access to `output` (the source node's output dict)
    and the built-in `len()` function only.

    Returns True if the condition passes, False otherwise.
    Raises ConditionEvaluationError on syntax or evaluation errors.
    """
    try:
        tree = ast.parse(expression, mode="eval")
        _validate_ast(tree)   # whitelist check
        result = eval(
            compile(tree, "<condition>", "eval"),
            {"__builtins__": {"len": len}},
            {"output": output},
        )
        return bool(result)
    except Exception as exc:
        raise ConditionEvaluationError(
            f"Condition '{expression}' failed: {exc}"
        ) from exc


class ConditionEvaluationError(RuntimeError):
    pass
```

`_validate_ast()` walks the AST and raises `ConditionEvaluationError` if any node type outside the allowed set is found (no imports, no function calls except `len`, no attribute access on non-`output` names).

### Execution Integration

In the execution loop, after assembling inputs from upstream outputs:

```python
for edge in pipeline_cfg.edges:
    if edge.dst_id != node_id:
        continue
    if edge.condition is not None:
        src_outputs = node_outputs[edge.src_id]
        try:
            passes = evaluate_condition(edge.condition, src_outputs)
        except ConditionEvaluationError as exc:
            logger.node_error(node_type, idx, exc)
            raise
        if not passes:
            # Mark port as None — do not transmit
            inputs[edge.dst_port] = None
            continue
    # Normal transmission
    inputs[edge.dst_port] = node_outputs[edge.src_id].get(edge.src_port)
```

After assembling all inputs, check for required ports receiving `None` due to false conditions:

```python
for port_name, port in node.input_ports.items():
    if port.required and inputs.get(port_name) is None:
        # Check if this None came from a false condition
        false_condition_ports = {
            e.dst_port for e in pipeline_cfg.edges
            if e.dst_id == node_id and e.condition is not None
            and not _condition_passed(e, node_outputs)
        }
        if port_name in false_condition_ports:
            logger.node_skip(node_id, node_type, reason="condition_false")
            node_outputs[node_id] = {}   # empty outputs
            skip_node = True
            break
```

### Example Graph

```json
{
  "schema_version": "1.1",
  "nodes": [
    {"id": "input_0", "node_type": "input", "config": {}},
    {"id": "clean_0", "node_type": "clean", "config": {}},
    {"id": "export_long", "node_type": "export", "config": {"suffix": "long"}},
    {"id": "export_short", "node_type": "export", "config": {"suffix": "short"}}
  ],
  "edges": [
    {"src_id": "input_0", "src_port": "output", "dst_id": "clean_0", "dst_port": "input"},
    {
      "src_id": "clean_0", "src_port": "output",
      "dst_id": "export_long", "dst_port": "input",
      "condition": "len(output['output']) > 10"
    },
    {
      "src_id": "clean_0", "src_port": "output",
      "dst_id": "export_short", "dst_port": "input",
      "condition": "len(output['output']) <= 10"
    }
  ]
}
```

---

## Files Modified

| File | Change |
|---|---|
| `app/core/ir/models.py` | Add `condition: str | None = None` to `IREdge` |
| `app/core/ir/loader.py` | Bump `SUPPORTED_MINOR_MAX` to 1; accept `"1.0"` as `"1.1"` |
| `app/core/pipeline.py` | Integrate condition evaluation in execution loop |
| `app/core/logger.py` | `node_skip()` already added in req-02; reused here |

## Files Created

| File | Purpose |
|---|---|
| `app/core/conditions.py` | `evaluate_condition()`, `ConditionEvaluationError`, `_validate_ast()` |
| `tests/test_conditional_branching.py` | Tests for condition evaluation, false-condition skip, error handling |
