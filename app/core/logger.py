# app/core/logger.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Structured event logging for pipeline execution. Emits typed
                  events to an in-memory deque and an optional streaming queue.
Owns:             PipelineLogger — all pipeline/node lifecycle event methods.
Public Surface:   PipelineLogger (pipeline_start, node_start, node_end,
                  node_error, node_skip, wave_start, wave_end, summary, etc.)
Must NOT:         Import from app.domain, app.api, or any execution module.
                  Must not persist logs directly (that is run_journal's job).
Dependencies:     stdlib (logging, time, collections, queue, datetime).
Reason To Change: New event types are added, log format changes, or the
                  bounded deque size policy changes.
"""

import logging
import time
from collections import deque
from datetime import datetime, timezone
from queue import Queue

_log = logging.getLogger(__name__)

# Maximum number of log entries kept in memory per logger instance (B-09 fix).
# Prevents unbounded memory growth for long-running pipelines.
_MAX_LOG_ENTRIES = 10_000


class PipelineLogger:
    def __init__(self, queue: Queue | None = None):
        # Use a bounded deque so the logs list never grows beyond _MAX_LOG_ENTRIES (B-09 fix)
        self.logs: deque = deque(maxlen=_MAX_LOG_ENTRIES)
        self.start_time = time.time()
        self.queue = queue  # for streaming to frontend

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _emit(self, entry):
        self.logs.append(entry)
        level = entry.get("level", "INFO").upper()
        msg = entry["message"]
        if level == "ERROR":
            _log.error(msg)
        elif level == "WARNING":
            _log.warning(msg)
        else:
            _log.info(msg)
        if self.queue:
            try:
                self.queue.put_nowait(entry)
            except Exception:
                # Queue full or closed — drop the entry rather than blocking
                # the pipeline execution thread (bounded-queue / dead-consumer guard).
                pass

    def _emit_structured(self, entry: dict):
        """Append a typed event to logs, put it on the queue, and write a
        DEBUG-level line to the Python logging system so structured events
        appear in log files when the handler level is DEBUG or lower.

        Plain-text events (INFO/WARNING/ERROR) continue to go through
        ``_emit`` which writes at the appropriate level.

        Queue delivery is best-effort: if the queue is full or closed the
        entry is dropped rather than blocking the caller.
        """
        self.logs.append(entry)
        event_type = entry.get("type", "event")
        _log.debug("structured_event type=%s %s", event_type, entry)
        if self.queue:
            try:
                self.queue.put_nowait(entry)
            except Exception:
                # Queue full or closed — drop rather than block.
                pass

    def log(self, level, message):
        entry = {
            "time": self._timestamp(),
            "level": level,
            "message": message,
        }
        self._emit(entry)

    def info(self, msg):
        self.log("INFO", msg)

    def error(self, msg):
        self.log("ERROR", msg)

    def pipeline_start(self, total_nodes: int, partial: bool = False, included_nodes: list[str] | None = None):
        self.info(f"Pipeline starting — {total_nodes} node{'s' if total_nodes != 1 else ''}")
        event = {
            "type": "pipeline_start",
            "total_nodes": total_nodes,
            "timestamp": self._timestamp(),
        }
        if partial:
            event["partial"] = True
        if included_nodes is not None:
            event["included_nodes"] = included_nodes
        self._emit_structured(event)

    def node_start(self, node_type, index, total_nodes=None):
        self.info(f"[{index}] {node_type} — starting")
        event = {
            "type": "node_start",
            "node_type": node_type,
            "node_index": index,
            "timestamp": self._timestamp(),
        }
        if total_nodes is not None:
            event["total_nodes"] = total_nodes
        self._emit_structured(event)

    def node_end(self, node_type, index, duration, output_count: int = 0):
        """Emit a node_end event.

        Args:
            output_count: Total number of output items across all ports
                          (sum of list lengths for list-typed ports, 1 for
                          scalar ports). Not a port count.
        """
        count_str = f" → {output_count} output items" if output_count else ""
        self.info(f"[{index}] {node_type} — done in {duration:.3f}s{count_str}")
        # Use "duration_s" consistently across all events (B-10 fix)
        self._emit_structured({
            "type": "node_end",
            "node_type": node_type,
            "node_index": index,
            "duration_s": duration,
            "output_count": output_count,
            "timestamp": self._timestamp(),
        })

    def node_error(self, node_type, index, error):
        self.error(f"[{index}] {node_type} — FAILED: {error}")
        self._emit_structured({
            "type": "node_error",
            "node_type": node_type,
            "node_index": index,
            "error_message": str(error),
            "error_type": type(error).__name__,
            "timestamp": self._timestamp(),
        })

    def pipeline_done(self, run_id: str, duration: float):
        self._emit_structured({
            "type": "done",
            "run_id": run_id,
            "duration_s": duration,
            "timestamp": self._timestamp(),
        })

    def pipeline_error(self, message: str):
        self._emit_structured({
            "type": "error",
            "message": message,
            "timestamp": self._timestamp(),
        })

    def pipeline_summary(self, stats_dict: dict):
        self._emit_structured({
            "type": "pipeline_summary",
            **stats_dict,
            "timestamp": self._timestamp(),
        })

    def wave_start(self, wave_index: int, node_ids: list[str]):
        """Emit a wave_start event at the beginning of a parallel execution wave.

        Req 1.6 (parallel execution wave events)
        """
        self._emit_structured({
            "type": "wave_start",
            "wave_index": wave_index,
            "node_ids": node_ids,
            "timestamp": self._timestamp(),
        })

    def wave_end(self, wave_index: int, node_ids: list[str], duration_s: float):
        """Emit a wave_end event at the end of a parallel execution wave.

        Req 1.6 (parallel execution wave events)
        """
        self._emit_structured({
            "type": "wave_end",
            "wave_index": wave_index,
            "node_ids": node_ids,
            "duration_s": duration_s,
            "timestamp": self._timestamp(),
        })

    def node_skip(self, node_id: str, node_type: str, reason: str):
        """Emit a node_skip event when a node is skipped (e.g. resumed from checkpoint).

        Req 3.9 (resume node_skip event)
        """
        self.info(f"[skip] {node_type} ({node_id}) — {reason}")
        self._emit_structured({
            "type": "node_skip",
            "node_id": node_id,
            "node_type": node_type,
            "reason": reason,
            "timestamp": self._timestamp(),
        })

    def event_received(self, source_type: str, node_id: str, payload_keys: list[str]):
        """Emit an event_received event when an EventSource fires.

        Req 6.7
        """
        self.info(f"[event] {source_type} → {node_id} ({', '.join(payload_keys)})")
        self._emit_structured({
            "type": "event_received",
            "source_type": source_type,
            "node_id": node_id,
            "payload_keys": payload_keys,
            "timestamp": self._timestamp(),
        })

    def warning(self, msg: str) -> None:
        """Emit a WARNING-level log entry."""
        self.log("WARNING", msg)

    def pipeline_paused(self, run_id: str) -> None:
        """Emit a pipeline_paused event when the pipeline transitions to paused state."""
        self.info(f"Pipeline paused — run {run_id}")
        self._emit_structured({
            "type": "pipeline_paused",
            "run_id": run_id,
            "timestamp": self._timestamp(),
        })

    def pipeline_resumed(self, run_id: str) -> None:
        """Emit a pipeline_resumed event when the pipeline resumes from paused state."""
        self.info(f"Pipeline resumed — run {run_id}")
        self._emit_structured({
            "type": "pipeline_resumed",
            "run_id": run_id,
            "timestamp": self._timestamp(),
        })

    def pipeline_cancelled(self, run_id: str, nodes_completed: int, nodes_remaining: int) -> None:
        """Emit a pipeline_cancelled event when the pipeline is cancelled."""
        self.info(
            f"Pipeline cancelled — run {run_id} "
            f"({nodes_completed} completed, {nodes_remaining} remaining)"
        )
        self._emit_structured({
            "type": "pipeline_cancelled",
            "run_id": run_id,
            "nodes_completed": nodes_completed,
            "nodes_remaining": nodes_remaining,
            "timestamp": self._timestamp(),
        })

    def summary(self) -> None:
        """Emit a structured pipeline_summary event and write a plain-text
        completion line to Python logging only (not the queue).

        The queue receives exactly one entry: the structured ``pipeline_summary``
        event. The plain-text line goes to the Python logging system so it
        appears in log files without creating a duplicate queue entry.
        """
        total = time.time() - self.start_time
        # Write plain-text line directly to Python logging — not through _emit
        # so it does not produce a second queue entry alongside the structured event.
        _log.info("Pipeline completed in %.3fs", total)
        self._emit_structured({
            "type": "pipeline_summary",
            "duration_s": round(total, 3),
            "timestamp": self._timestamp(),
        })
