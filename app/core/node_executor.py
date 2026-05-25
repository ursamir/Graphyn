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

    Observer contract
    -----------------
    ``Node.on_start()``, ``Node.on_end()``, and ``Node.on_error()`` in
    ``base.py`` already call the observer internally.  This executor does NOT
    call the observer directly — doing so would fire every event twice (BUG-1
    fix).  The executor's only job is to call the lifecycle hooks in the right
    order; the hooks own the observer notification.

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
        node_type = type(node).__name__

        last_exc: Exception | None = None

        for attempt in range(max_attempts):
            if attempt > 0 and policy:
                wait = policy.wait_before_attempt(attempt - 1)
                if wait > 0:
                    time.sleep(wait)

            try:
                # on_start() calls observer.on_node_start() internally (base.py).
                # Do NOT call observer directly here — that would fire the event twice.
                node._current_run_id = self._run_id  # type: ignore[attr-defined]
                node.on_start()
            except Exception as exc:
                # on_error() calls observer.on_node_error() internally.
                node.on_error(exc)
                last_exc = exc
                continue

            t0 = time.perf_counter()
            try:
                outputs = node.process(inputs)
            except Exception as exc:
                # on_error() calls observer.on_node_error() internally.
                node.on_error(exc)
                last_exc = exc
                continue

            duration = time.perf_counter() - t0

            # on_end() calls observer.on_node_end() internally.
            # SA-NE2: pass duration and port counts via the node's _last_duration/
            # _last_counts attributes so base.py can forward them to the observer.
            # These are side-channel attributes on a foreign object — a known
            # quality issue (SA-NE2). The proper fix is to add explicit parameters
            # to on_end(duration, input_counts, output_counts) in a future refactor.
            node._last_duration = duration  # type: ignore[attr-defined]
            node._last_input_counts = {k: _count_port_items(v) for k, v in inputs.items()}  # type: ignore[attr-defined]
            node._last_output_counts = {k: _count_port_items(v) for k, v in outputs.items()}  # type: ignore[attr-defined]
            node.on_end()

            if attempt > 0:
                log.info("Node '%s' succeeded after %d attempt(s).", node_type, attempt + 1)

            return outputs

        # All attempts exhausted.
        # on_error() was already called inside the loop on the last failed attempt.
        # Do NOT call it again here — that would fire the event twice (BUG-6 fix).
        assert last_exc is not None
        # SA-NE1 fix: only call teardown() if setup() was previously called.
        # If on_start() raised on every attempt, setup() may have succeeded but
        # teardown() should still be guarded by _setup_done.
        if self._setup_done:
            self.teardown()
        raise last_exc

    async def execute_stream(
        self, inputs: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute the node in streaming mode.

        on_start() and on_end() (which call the observer internally) are called
        once per stream invocation. on_end() fires in a finally block so it
        fires even when the caller breaks out of the async for early.

        SA-NE3: Streaming nodes do not use RetryPolicy. This is an intentional
        asymmetry — wrapping an async generator in a retry loop requires
        re-entering the generator from the start, which is not always safe for
        stateful streaming nodes. If retry is needed, override execute_stream
        in the node subclass and implement the retry loop there.
        """
        node = self._node
        node._current_run_id = self._run_id  # type: ignore[attr-defined]
        node.on_start()
        try:
            async for item in node.process_stream(inputs):
                yield item
        except Exception as exc:
            node.on_error(exc)
            raise
        finally:
            node.on_end()
