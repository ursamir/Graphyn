"""Mode B remote wait: backoff polls + immediate Waiting-for-worker journal note."""
from __future__ import annotations

import time
from typing import Any

import pytest

from app.core.distributed import backend as backend_mod
from app.core.logger import PipelineLogger


class _FakeRun:
    run_id = "run-wait-1"
    is_cancelled = False
    is_paused = False
    logs: list = []

    def save_logs(self, logs):  # noqa: ANN001
        self.logs = list(logs)

    def _write_meta_field(self, *a, **k):  # noqa: ANN001, ARG002
        return None

    def wait_if_paused(self):
        return None


class _FakeQueue:
    def __init__(self, ready_after: float):
        self.ready_after = ready_after
        self.t0 = time.monotonic()
        self.wait_calls: list[float] = []
        self.cancelled = []

    def cancel(self, job_id):  # noqa: ANN001
        self.cancelled.append(job_id)

    def set_run_paused(self, *a, **k):  # noqa: ANN001, ARG002
        return None

    def list_events(self, job_id):  # noqa: ANN001, ARG002
        return []

    def wait_for_result(self, job_id, *, timeout_s=None, poll_interval_s=None):  # noqa: ANN001, ARG002
        self.wait_calls.append(float(timeout_s if timeout_s is not None else 0))
        if time.monotonic() - self.t0 >= self.ready_after:
            return {"status": "succeeded", "job_id": job_id}
        # Simulate blocking for the requested slice without sleeping wall-clock long
        # in CI — the caller already chose timeout_s as the backoff slice.
        return None

    def ack(self, job_id):  # noqa: ANN001, ARG002
        return None


def test_wait_remote_result_emits_immediate_note_and_backs_off(monkeypatch):
    monkeypatch.setenv("GRAPHYN_JOB_WAIT_POLL_S", "0.25")
    # Avoid real ack path depending on queue.ack name
    monkeypatch.setattr(backend_mod, "_ack", lambda queue, job_id: None)

    run = _FakeRun()
    logger = PipelineLogger()
    q = _FakeQueue(ready_after=0.9)

    t0 = time.monotonic()
    result = backend_mod._wait_remote_result(
        q, run, "job-abc-12345678", timeout_s=5.0, logger=logger, node_id="trainer_0"
    )
    elapsed = time.monotonic() - t0

    assert result is not None
    assert any("Waiting for worker on node trainer_0" in str(e.get("message", "")) for e in logger.logs)
    # First note flushed immediately (before long waits accumulate).
    assert run.logs, "logs should be flushed to the run journal"
    # Backoff: later wait slices should grow (not stay stuck at tiny polls forever).
    assert len(q.wait_calls) >= 2
    assert q.wait_calls[0] == pytest.approx(0.25)
    assert q.wait_calls[1] > q.wait_calls[0]
    # Capped at 5× the base slice (never unbounded).
    assert max(q.wait_calls) <= 0.25 * 5 + 1e-9
    assert elapsed < 4.0


def test_wait_remote_result_stops_waiting_after_progress(monkeypatch):
    """Once node_progress lands, do not resume Waiting heartbeats between epochs."""
    monkeypatch.setenv("GRAPHYN_JOB_WAIT_POLL_S", "0.2")
    monkeypatch.setattr(backend_mod, "_ack", lambda queue, job_id: None)

    class _ProgressQueue(_FakeQueue):
        def list_events(self, job_id):  # noqa: ANN001, ARG002
            # Emit one progress event after the first wait poll.
            if time.monotonic() - self.t0 >= 0.35:
                return [
                    {
                        "_seq": 1,
                        "type": "node_progress",
                        "node_id": "trainer_0",
                        "epoch": 1,
                        "epochs": 50,
                    }
                ]
            return []

    run = _FakeRun()
    logger = PipelineLogger()
    q = _ProgressQueue(ready_after=1.2)

    backend_mod._wait_remote_result(
        q, run, "job-prog-12345678", timeout_s=5.0, logger=logger, node_id="trainer_0"
    )
    waiting = [e for e in logger.logs if "Waiting for worker" in str(e.get("message", ""))]
    latest = getattr(run, "_latest_node_progress", None) or {}
    # At least one Waiting before progress; none after the first progress landed.
    assert waiting, "expected an initial Waiting note before the worker reports progress"
    assert "trainer_0" in latest
    # All Waiting notes must have been emitted before progress_seen latches —
    # i.e. count stays small (claim phase only), not one-per-poll for the whole wait.
    assert len(waiting) <= 3
