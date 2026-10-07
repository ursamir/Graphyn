# app/core/distributed/worker_progress.py
"""
Bounded Context:  BC5 — Execution Runtime (Mode B worker progress)
Responsibility:   Bridge ``emit_node_progress`` on a worker into the control
                  plane's per-job event log (``POST /jobs/{id}/events`` or
                  in-process ``JobQueue.append_events``) so the control
                  ``_forward_job_events`` path can write the same
                  ``node_progress`` journal rows Mode A already produces.
Owns:             JobProgressPublisher (batched, best-effort, never fatal).
Public Surface:   JobProgressPublisher
Must NOT:         Import app.api / app.domain; block the training thread on
                  a slow control plane (flush runs on a daemon thread).
Dependencies:     stdlib (threading, time, logging).
Reason To Change: Job event protocol or progress batching policy changes.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

PostEvents = Callable[[str, list[dict[str, Any]]], Any]


class JobProgressPublisher:
    """Buffer node_progress (and other sink) events; flush to the control plane.

    ``post_events(job_id, events)`` is the only I/O — HTTP or in-process queue.
    Failures are logged and dropped so training is never aborted by progress.
    """

    def __init__(
        self,
        job_id: str,
        post_events: PostEvents,
        *,
        flush_interval_s: float = 1.0,
        batch_size: int = 8,
    ) -> None:
        self._job_id = str(job_id)
        self._post = post_events
        self._interval = max(0.2, float(flush_interval_s))
        self._batch = max(1, int(batch_size))
        self._buf: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"graphyn-job-progress-{self._job_id[:12]}",
            daemon=True,
        )
        self._thread.start()

    def sink(self, event: dict[str, Any]) -> None:
        """NodeExecutor progress sink — receives a full journal event dict."""
        if not isinstance(event, dict):
            return
        # Drop worker-local noise that must not round-trip as job events.
        et = str(event.get("type") or "")
        if et in ("outputs", "provenance"):
            return
        with self._lock:
            self._buf.append(dict(event))
            pending = len(self._buf)
        if pending >= self._batch:
            self._wake.set()

    def close(self) -> None:
        """Stop the flusher and push any remaining events (best-effort)."""
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=max(3.0, self._interval * 3))
        self._flush()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=self._interval)
            self._wake.clear()
            self._flush()
            if self._stop.is_set():
                break

    def _flush(self) -> None:
        with self._lock:
            if not self._buf:
                return
            batch, self._buf = self._buf, []
        try:
            self._post(self._job_id, batch)
        except Exception as exc:
            log.debug(
                "job progress flush failed for %s (%d events): %s",
                self._job_id,
                len(batch),
                exc,
            )
            # Re-queue once so a transient blip does not drop an epoch forever;
            # a second failure drops them (cap growth under prolonged outage).
            with self._lock:
                if not self._stop.is_set() and len(self._buf) < 200:
                    self._buf = batch + self._buf


__all__ = ["JobProgressPublisher", "PostEvents"]
