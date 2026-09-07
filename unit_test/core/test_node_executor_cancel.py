"""NodeExecutor cooperative cancel between retries / before process."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.node_executor import NodeExecutor
from app.core.nodes.retry import RetryPolicy


def _mock_node(*, max_attempts: int = 3, backoff: float = 0.4):
    node = MagicMock()
    node.retry_policy = RetryPolicy(
        max_attempts=max_attempts,
        backoff_seconds=backoff,
        backoff_multiplier=1.0,
        max_wait_seconds=backoff,
    )
    node.config = None
    return node


def test_request_cancel_aborts_before_first_attempt():
    node = _mock_node()
    ex = NodeExecutor(node, run_id="r1")
    ex._setup_done = True
    ex.request_cancel()
    with pytest.raises(RuntimeError, match="cancelled by control plane"):
        ex.execute({"input": 1})
    node.on_start.assert_not_called()


def test_cancel_check_during_backoff_stops_retry():
    node = _mock_node(max_attempts=3, backoff=0.5)
    attempts = {"n": 0}

    def flaky(_node, _inputs):
        attempts["n"] += 1
        raise RuntimeError("transient")

    ex = NodeExecutor(node, run_id="r2")
    ex._setup_done = True
    ex._process = flaky  # type: ignore[method-assign]

    def check():
        return attempts["n"] >= 1

    ex.set_cancel_check(check)
    with pytest.raises(RuntimeError, match="cancelled by control plane"):
        ex.execute({"input": 1})
    assert attempts["n"] == 1
    # on_error called for the failed attempt; second attempt never starts process
    assert node.on_error.called


def test_execute_stream_honours_request_cancel_before_start():
    """DIST-CANCEL-2: cancel before stream start aborts without process_stream."""
    import asyncio

    node = _mock_node()

    async def never_stream(_inputs):
        yield {"chunk": 1}
        raise AssertionError("process_stream should not run after cancel")

    node.process_stream = never_stream
    ex = NodeExecutor(node, run_id="r-stream-1")
    ex._setup_done = True
    ex.request_cancel()

    async def _run():
        async for _ in ex.execute_stream({"input": 1}):
            pass

    with pytest.raises(RuntimeError, match="cancelled by control plane"):
        asyncio.run(_run())
    node.on_start.assert_not_called()


def test_execute_stream_honours_cancel_between_items():
    """DIST-CANCEL-2: cancel between yields stops further items (cooperative)."""
    import asyncio

    node = _mock_node()
    emitted = {"n": 0}

    async def slow_stream(_inputs):
        for i in range(5):
            emitted["n"] += 1
            yield {"chunk": i}

    node.process_stream = slow_stream
    ex = NodeExecutor(node, run_id="r-stream-2")
    ex._setup_done = True

    def check():
        return emitted["n"] >= 2

    ex.set_cancel_check(check)

    async def _run():
        got = []
        async for item in ex.execute_stream({"input": 1}):
            got.append(item)
        return got

    with pytest.raises(RuntimeError, match="cancelled by control plane"):
        asyncio.run(_run())
    # cancel_check trips when emitted>=2, which is at the start of the 2nd
    # loop iteration — so only the first yielded item was delivered.
    assert emitted["n"] >= 2

