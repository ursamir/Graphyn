#!/usr/bin/env python3
"""
Example 20 — Retry and Fault Tolerance (Priority 14 — F4)
==========================================================
Demonstrates RetryPolicy with exponential backoff — a node that
intermittently fails is retried automatically with increasing delays.

What this shows:
  - RetryPolicy(max_attempts=3, backoff_seconds=0.5, backoff_multiplier=2.0)
  - NodeExecutor retry loop: on_start → process → on_error → retry
  - node_error log events with attempt number
  - Exponential backoff: 0.5s → 1.0s → 2.0s between attempts
  - How to attach a RetryPolicy to a node via NodeMetadata
  - NodeObserver — hook into node lifecycle events

Usage:
  venv/bin/python examples/20_retry_fault_tolerance/retry_demo.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import ClassVar

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

_RESET = "\033[0m"; _BOLD = "\033[1m"; _CYAN = "\033[36m"
_GREEN = "\033[32m"; _DIM = "\033[2m"; _YELLOW = "\033[33m"; _RED = "\033[31m"
def _h(t): return f"{_BOLD}{_CYAN}{t}{_RESET}"
def _ok(t): return f"{_GREEN}{t}{_RESET}"
def _dim(t): return f"{_DIM}{t}{_RESET}"
def _warn(t): return f"{_YELLOW}{t}{_RESET}"
def _err(t): return f"{_RED}{t}{_RESET}"

EXAMPLE_DIR = Path(__file__).parent


# ── Flaky node that fails N times before succeeding ───────────────────────────

from app.core.nodes.base import Node  # noqa: E402
from app.core.nodes.config import NodeConfig  # noqa: E402
from app.core.nodes.metadata import NodeMetadata  # noqa: E402
from app.core.nodes.ports import InputPort, OutputPort  # noqa: E402
from app.core.nodes.retry import RetryPolicy  # noqa: E402
from app.core.nodes.observers import NodeObserver  # noqa: E402


class FlakyConfig(NodeConfig):
    fail_first_n: int = 2   # fail this many times before succeeding
    failure_rate: float = 0.0  # 0 = deterministic, >0 = random


class FlakyNode(Node):
    """A node that fails the first N times, then succeeds.

    Used to demonstrate RetryPolicy with exponential backoff.
    """
    node_type: ClassVar[str] = "_flaky_node_demo"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="_flaky_node_demo",
        label="Flaky Node",
        description="Fails the first N times, then succeeds. For retry demo.",
        category="Demo",
    )
    input_ports:  ClassVar[dict] = {}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(FlakyConfig):
        pass

    def __init__(self, config=None, seed: int = 0, observer=None) -> None:
        super().__init__(config=config, seed=seed, observer=observer)
        self._attempt = 0
        # Attach a RetryPolicy: 3 attempts, 0.5s base, 2× multiplier
        self.retry_policy = RetryPolicy(
            max_attempts=3,
            backoff_seconds=0.5,
            backoff_multiplier=2.0,
        )

    def process(self, inputs: dict) -> dict:
        self._attempt += 1
        if self._attempt <= self.config.fail_first_n:
            raise RuntimeError(
                f"Simulated failure on attempt {self._attempt} "
                f"(will succeed after {self.config.fail_first_n} failures)"
            )
        return {"output": [f"success_after_{self._attempt}_attempts"]}


# ── Observer that logs retry events ──────────────────────────────────────────

class RetryObserver(NodeObserver):
    """Logs node lifecycle events to the terminal."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def on_node_start(self, node_type: str, run_id: str) -> None:
        self.events.append({"type": "start", "node_type": node_type})
        print(f"  {_dim('→')} {node_type} starting...")

    def on_node_end(self, node_type: str, run_id: str, duration: float,
                    input_counts: dict, output_counts: dict) -> None:
        self.events.append({"type": "end", "node_type": node_type, "duration": duration})
        print(f"  {_ok('✓')} {node_type} succeeded in {duration:.3f}s")

    def on_node_error(self, node_type: str, run_id: str, error: Exception) -> None:
        self.events.append({"type": "error", "node_type": node_type, "error": str(error)})
        print(f"  {_err('✗')} {node_type} failed: {_dim(str(error)[:60])}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    from app.core.registry_runtime import get_registry
    from app.core.nodes.metadata import NodeMetadata
    from app.core.pipeline import NodeExecutor

    registry = get_registry()
    if "_flaky_node_demo" not in registry:
        registry.register("_flaky_node_demo", FlakyNode, FlakyNode.metadata)

    print(f"\n{'='*60}")
    print(_h("Example 20 — Retry and Fault Tolerance"))
    print(f"{'='*60}")

    # ── Demo 1: Node fails twice, succeeds on 3rd attempt ─────────────
    print(f"\n{_h('Demo 1 — Fail 2 times, succeed on 3rd attempt')}")
    print(f"  RetryPolicy: max_attempts=3, backoff=0.5s, multiplier=2.0×")
    print(f"  Expected backoff: 0.5s before attempt 2, 1.0s before attempt 3")

    observer = RetryObserver()
    node = FlakyNode(config={"fail_first_n": 2}, seed=0, observer=observer)
    executor = NodeExecutor(node, run_id="demo-retry")
    executor.setup()

    t0 = time.perf_counter()
    try:
        result = executor.execute({})
        elapsed = time.perf_counter() - t0
        print(f"\n  {_ok('✓')} Final result: {result}")
        print(f"  Total time (including backoff): {elapsed:.2f}s")
        print(f"  Expected: ~1.5s (0.5s + 1.0s backoff)")
    except Exception as exc:
        print(f"  {_err('✗')} All attempts exhausted: {exc}")
    finally:
        executor.teardown()

    # Show event log
    print(f"\n  Observer events:")
    for e in observer.events:
        if e["type"] == "start":
            print(f"    {_dim('→')} on_node_start({e['node_type']})")
        elif e["type"] == "end":
            print(f"    {_ok('✓')} on_node_end({e['node_type']}, duration={e['duration']:.3f}s)")
        elif e["type"] == "error":
            print(f"    {_err('✗')} on_node_error({e['node_type']}, {e['error'][:40]})")

    # ── Demo 2: All attempts exhausted ────────────────────────────────
    print(f"\n{_h('Demo 2 — All 3 attempts fail (fail_first_n=5)')}")
    print(f"  RetryPolicy: max_attempts=3 — will exhaust all attempts")

    observer2 = RetryObserver()
    node2 = FlakyNode(config={"fail_first_n": 5}, seed=0, observer=observer2)
    executor2 = NodeExecutor(node2, run_id="demo-exhaust")
    executor2.setup()

    t0 = time.perf_counter()
    try:
        executor2.execute({})
        print(f"  {_warn('⚠')} Unexpected success")
    except RuntimeError as exc:
        elapsed = time.perf_counter() - t0
        print(f"  {_ok('✓')} Correctly raised RuntimeError after all attempts")
        print(f"  Error: {_dim(str(exc)[:60])}")
        print(f"  Total time: {elapsed:.2f}s (0.5s + 1.0s backoff)")
    finally:
        executor2.teardown()

    # ── Demo 3: RetryPolicy math ───────────────────────────────────────
    print(f"\n{_h('Demo 3 — RetryPolicy backoff calculation')}")
    policy = RetryPolicy(max_attempts=5, backoff_seconds=1.0, backoff_multiplier=2.0)
    print(f"  RetryPolicy(max_attempts=5, backoff_seconds=1.0, backoff_multiplier=2.0)")
    print(f"  Attempt 1: execute immediately")
    for i in range(4):
        wait = policy.wait_before_attempt(i)
        print(f"  Attempt {i+2}: wait {wait:.1f}s before retry")

    print(f"\n{_h('Summary')}")
    print(f"  RetryPolicy is attached to a node at construction time.")
    print(f"  NodeExecutor handles the retry loop automatically.")
    print(f"  NodeObserver hooks: on_node_start, on_node_end, on_node_error")
    print(f"  All retry attempts are logged as node_error events.")
    print(f"  After max_attempts, the last exception is re-raised.")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
