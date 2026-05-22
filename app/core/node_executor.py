# app/core/node_executor.py
"""NodeExecutor — drives a single node through its full lifecycle with retry.

Extracted from pipeline.py. Responsible for:
  - setup / teardown lifecycle
  - on_start → process → on_end sequencing
  - exponential back-off retry via RetryPolicy
  - streaming execution via process_stream()
  - _count_port_items helper
"""
from __future__ import annotations

import logging
import time
from typing import Any, AsyncGenerator

from app.core.nodes.base import Node
from app.core.nodes.observers import NodeObserver
from app.core.nodes.retry import RetryPolicy

log = logging.getLogger(__name__)


def _count_port_items(port_data: Any) -> int:
    """Return the number of items on a port (1 for single value, N for list, 0 for None)."""
    if isinstance(port_data, list):
        return len(port_data)
    if port_data is None:
        return 0
    return 1


class NodeExecutor:
    """Drives a single node through setup → (on_start → process → on_end)* → teardown.

    Handles:
      - Lifecycle hook sequencing
      - Retry with exponential back-off (via node.retry_policy)
      - Observer event emission
      - Streaming vs. batch execution

    Usage::

        executor = NodeExecutor(node, run_id="run-abc")
        executor.setup()
        outputs = executor.execute({"input": data})
        executor.teardown()
    """

    def __init__(self, node: Node, run_id: str = "") -> None:
        self._node = node
        self._run_id = run_id
        self._setup_done = False

    def setup(self) -> None:
        """Call node.setup() once before the first execution. Subsequent calls are no-ops."""
        if not self._setup_done:
            self._node.setup()
            self._setup_done = True

    def teardown(self) -> None:
        """Call node.teardown() to release resources."""
        self._node.teardown()

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute the node synchronously with full lifecycle + retry.

        Args:
            inputs: Dict mapping input port names to their values.

        Returns:
            Dict mapping output port names to their produced values.

        Raises:
            Exception: The last exception raised by process() after all retry
                       attempts are exhausted.
        """
        node = self._node
        policy: RetryPolicy | None = node.retry_policy
        max_attempts = policy.max_attempts if policy else 1
        observer: NodeObserver | None = node.observer
        node_type = type(node).__name__

        last_exc: Exception | None = None

        for attempt in range(max_attempts):
            if attempt > 0 and policy:
                wait = policy.wait_before_attempt(attempt - 1)
                if wait > 0:
                    time.sleep(wait)

            try:
                node.on_start()
                if observer:
                    observer.on_node_start(node_type, self._run_id)
            except Exception as exc:
                node.on_error(exc)
                if observer:
                    observer.on_node_error(node_type, self._run_id, exc)
                last_exc = exc
                continue

            t0 = time.perf_counter()
            try:
                outputs = node.process(inputs)
            except Exception as exc:
                node.on_error(exc)
                if observer:
                    observer.on_node_error(node_type, self._run_id, exc)
                last_exc = exc
                continue

            duration = time.perf_counter() - t0

            node.on_end()
            input_counts = {k: _count_port_items(v) for k, v in inputs.items()}
            output_counts = {k: _count_port_items(v) for k, v in outputs.items()}
            if observer:
                observer.on_node_end(node_type, self._run_id, duration, input_counts, output_counts)

            if attempt > 0:
                log.info("Node '%s' succeeded after %d attempt(s).", node_type, attempt + 1)

            return outputs

        assert last_exc is not None
        node.on_error(last_exc)
        if observer:
            observer.on_node_error(node_type, self._run_id, last_exc)
        self.teardown()
        raise last_exc

    async def execute_stream(
        self, inputs: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute the node in streaming mode.

        on_end() is called in a finally block so it fires even when the caller
        breaks out of the async for early.
        """
        node = self._node
        node.on_start()
        try:
            async for item in node.process_stream(inputs):
                yield item
        except Exception as exc:
            node.on_error(exc)
            raise
        finally:
            node.on_end()
