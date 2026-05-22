# Example 20 — Retry and Fault Tolerance

Demonstrates `RetryPolicy` with exponential backoff — a node that intermittently fails is retried automatically with increasing delays between attempts.

---

## What This Demonstrates

- `RetryPolicy(max_attempts=3, backoff_seconds=0.5, backoff_multiplier=2.0)`
- `NodeExecutor` retry loop: `on_start → process → on_error → wait → retry`
- `node_error` log events with attempt number
- Exponential backoff: 0.5s → 1.0s → 2.0s between attempts
- How to attach a `RetryPolicy` to a node via `NodeMetadata`
- `NodeObserver` — hook into node lifecycle events (`on_node_start`, `on_node_end`, `on_node_error`)

---

## How to Run

```bash
venv/bin/python examples/20_retry_fault_tolerance/retry_demo.py
```

---

## Expected Output

```
Demo 1 — Fail 2 times, succeed on 3rd attempt
  RetryPolicy: max_attempts=3, backoff=0.5s, multiplier=2.0×
  Expected backoff: 0.5s before attempt 2, 1.0s before attempt 3
  → FlakyNode starting...
  ✗ FlakyNode failed: Simulated failure on attempt 1
  → FlakyNode starting...
  ✗ FlakyNode failed: Simulated failure on attempt 2
  → FlakyNode starting...
  ✓ FlakyNode succeeded in 0.000s

  ✓ Final result: {'output': ['success_after_3_attempts']}
  Total time (including backoff): 1.50s
  Expected: ~1.5s (0.5s + 1.0s backoff)

  Observer events:
    → on_node_start(FlakyNode)
    ✗ on_node_error(FlakyNode, Simulated failure on attempt 1)
    → on_node_start(FlakyNode)
    ✗ on_node_error(FlakyNode, Simulated failure on attempt 2)
    → on_node_start(FlakyNode)
    ✓ on_node_end(FlakyNode, duration=0.000s)

Demo 3 — RetryPolicy backoff calculation
  Attempt 1: execute immediately
  Attempt 2: wait 1.0s before retry
  Attempt 3: wait 2.0s before retry
  Attempt 4: wait 4.0s before retry
  Attempt 5: wait 8.0s before retry
```

---

## Attaching a RetryPolicy to a Node

```python
from app.core.nodes.base import Node
from app.core.nodes.retry import RetryPolicy
from typing import ClassVar

class MyUnreliableNode(Node):
    node_type: ClassVar[str] = "my_unreliable_node"
    # ... metadata, ports, Config ...

    def __init__(self, config=None, seed: int = 0, observer=None) -> None:
        super().__init__(config=config, seed=seed, observer=observer)
        # Attach retry policy at construction time
        self.retry_policy = RetryPolicy(
            max_attempts=3,
            backoff_seconds=1.0,
            backoff_multiplier=2.0,
        )

    def process(self, inputs: dict) -> dict:
        # This may fail — NodeExecutor will retry automatically
        result = call_external_api(inputs)
        return {"output": result}
```

---

## RetryPolicy Backoff Formula

The wait before retry attempt `i` (0-indexed, where `i=0` is the first retry):

```
wait_i = backoff_seconds × (backoff_multiplier ^ i)
```

Examples with `backoff_seconds=1.0`, `backoff_multiplier=2.0`:
- Before 2nd attempt: `1.0 × 2.0^0 = 1.0s`
- Before 3rd attempt: `1.0 × 2.0^1 = 2.0s`
- Before 4th attempt: `1.0 × 2.0^2 = 4.0s`

---

## NodeObserver

`NodeObserver` lets you hook into node lifecycle events without modifying node code:

```python
from app.core.nodes.observers import NodeObserver

class MetricsObserver(NodeObserver):
    def on_node_start(self, node_type: str, run_id: str) -> None:
        print(f"Starting: {node_type}")

    def on_node_end(self, node_type: str, run_id: str, duration: float,
                    input_counts: dict, output_counts: dict) -> None:
        print(f"Done: {node_type} in {duration:.3f}s")

    def on_node_error(self, node_type: str, run_id: str, error: Exception) -> None:
        print(f"Error: {node_type}: {error}")

# Pass observer to pipeline
result = pipeline.run(observer=MetricsObserver())
```

---

## Use Cases

- **External API calls**: retry on transient network failures
- **GPU operations**: retry on out-of-memory errors with smaller batch sizes
- **File I/O**: retry on temporary filesystem unavailability
- **Database queries**: retry on connection timeouts
