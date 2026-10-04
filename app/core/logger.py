# app/core/logger.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Structured event logging for pipeline execution. Emits typed
                  events to an in-memory deque and an optional streaming queue.
Owns:             PipelineLogger — all pipeline/node lifecycle event methods.
Public Surface:   PipelineLogger (pipeline_start, node_start, node_end,
                  node_progress, node_error, node_skip, wave_start, wave_end, summary, etc.),
                  port_item_counts(), primary_output_count().
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

# Port whose item count is the node's headline ``output_count``.
PRIMARY_OUTPUT_PORT = "output"


def port_item_counts(outputs: dict | None) -> dict[str, int]:
    """Items per output port: list length, 0 for None, 1 for any other value."""
    counts: dict[str, int] = {}
    for port, value in (outputs or {}).items():
        if isinstance(value, list):
            counts[str(port)] = len(value)
        else:
            counts[str(port)] = 0 if value is None else 1
    return counts


def primary_output_count(port_counts: dict[str, int]) -> int:
    """Count of the ``output`` port when present, else the sum over all ports.

    Side ports (``rejected``, ``error`` …) of a node with a main ``output``
    port are not added, so a gate passing 206 of 219 reports 206.
    """
    if PRIMARY_OUTPUT_PORT in port_counts:
        return int(port_counts[PRIMARY_OUTPUT_PORT])
    return int(sum(port_counts.values()))

# Maximum number of log entries kept in memory per logger instance (B-09 fix).
# Prevents unbounded memory growth for long-running pipelines.
_MAX_LOG_ENTRIES = 10_000
# node_progress rows kept verbatim per node before thinning to every 10th.
_MAX_PROGRESS_PER_NODE = 500


class PipelineLogger:
    def __init__(self, queue: Queue | None = None):
        # Use a bounded deque so the logs list never grows beyond _MAX_LOG_ENTRIES (B-09 fix)
        self.logs: deque = deque(maxlen=_MAX_LOG_ENTRIES)
        self.start_time = time.time()
        self.queue = queue  # for streaming to frontend
        # node_id → human label ("Trainer · Path C (MobileNet · lr 0.002)");
        # set by the orchestrator, stamped as ``node_label`` on node events.
        self.node_labels: dict[str, str] = {}

    def set_node_labels(self, labels: dict | None) -> None:
        """Install node_id → label map used to stamp ``node_label`` on node events."""
        self.node_labels = {str(k): str(v) for k, v in (labels or {}).items() if v}

    def _stamp_label(self, entry: dict) -> None:
        labels = getattr(self, "node_labels", None)
        if not labels or not isinstance(entry, dict):
            return
        nid = entry.get("node_id")
        if nid is not None and "node_label" not in entry:
            label = labels.get(str(nid))
            if label:
                entry["node_label"] = label

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
        self._stamp_label(entry)
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

    def pipeline_start(
        self,
        total_nodes: int,
        partial: bool = False,
        included_nodes: list[str] | None = None,
        run_id: str | None = None,
    ):
        event = {
            "type": "pipeline_start",
            "total_nodes": total_nodes,
            "timestamp": self._timestamp(),
        }
        if run_id:
            event["run_id"] = run_id
        if partial:
            event["partial"] = True
        if included_nodes is not None:
            event["included_nodes"] = included_nodes
        _log.info(
            "Pipeline starting — %d node%s",
            total_nodes,
            "s" if total_nodes != 1 else "",
        )
        self._emit_structured(event)

    def node_start(self, node_type, index, total_nodes=None, node_id=None):
        event = {
            "type": "node_start",
            "node_type": node_type,
            "node_index": index,
            "timestamp": self._timestamp(),
        }
        if node_id:
            event["node_id"] = node_id
        if total_nodes is not None:
            event["total_nodes"] = total_nodes
        _log.info("[%s] %s — starting", index, node_type)
        self._emit_structured(event)

    def node_end(
        self,
        node_type,
        index,
        duration,
        output_count: int = 0,
        node_id=None,
        output_counts: dict[str, int] | None = None,
        extra: dict | None = None,
    ):
        """Emit a node_end event.

        ``extra`` (optional) is merged into the event without overriding the
        canonical keys — e.g. ``{"dataset": {...}}`` for ingest nodes.

        Args:
            output_count: Item count of the node's primary output (used when
                          ``output_counts`` is not given).
            output_counts: Per-port item counts (see :func:`port_item_counts`).
                          When given, ``output_count`` is derived from it via
                          :func:`primary_output_count` (the ``output`` port
                          when present — a gate's ``rejected`` port is not
                          added), and the event also carries
                          ``output_counts`` and ``rejected_count``.
        """
        if output_counts is not None:
            output_count = primary_output_count(output_counts)
        count_str = f" → {output_count} output items" if output_count else ""
        if output_counts and "rejected" in output_counts:
            count_str += f" ({output_counts['rejected']} rejected)"
        _log.info("[%s] %s — done in %.3fs%s", index, node_type, duration, count_str)
        # Use "duration_s" consistently across all events (B-10 fix)
        end_event = {
            "type": "node_end",
            "node_type": node_type,
            "node_index": index,
            "duration_s": duration,
            "output_count": output_count,
            "timestamp": self._timestamp(),
        }
        if output_counts is not None:
            end_event["output_counts"] = dict(output_counts)
            if "rejected" in output_counts:
                end_event["rejected_count"] = output_counts["rejected"]
        if node_id:
            end_event["node_id"] = node_id
        if isinstance(extra, dict):
            for key, value in extra.items():
                end_event.setdefault(str(key), value)
        self._emit_structured(end_event)

    def node_progress(self, event: dict) -> None:
        """Record a ``node_progress`` event (see app.core.nodes.progress).

        Always forwarded to the streaming queue; the in-memory journal keeps
        at most ``_MAX_PROGRESS_PER_NODE`` progress rows per node (older
        ones are thinned) so long trainings cannot evict lifecycle events
        from the bounded deque.
        """
        if not isinstance(event, dict):
            return
        entry = dict(event)
        entry.setdefault("type", "node_progress")
        entry.setdefault("timestamp", self._timestamp())
        self._stamp_label(entry)
        key = str(entry.get("node_id") or entry.get("node_type") or "")
        counts = getattr(self, "_progress_counts", None)
        if counts is None:
            counts = {}
            self._progress_counts = counts
        n = counts.get(key, 0) + 1
        counts[key] = n
        keep = n <= _MAX_PROGRESS_PER_NODE or n % 10 == 0 or entry.get("final") is True
        if keep:
            self.logs.append(entry)
        _log.debug("node_progress %s", entry.get("message"))
        if self.queue:
            try:
                self.queue.put_nowait(entry)
            except Exception:
                pass

    def node_error(self, node_type, index, error, node_id=None):
        """Emit ``node_error`` with the real exception type / message / traceback.

        Isolated plugin failures (``IsolatedNodeError``) carry the worker's
        exception type and traceback as attributes; everything else uses the
        host exception and its ``__traceback__``.
        """
        _log.error("[%s] %s — FAILED: %s", index, node_type, error)
        err_type = getattr(error, "error_type", None) or type(error).__name__
        tb_text = getattr(error, "traceback_text", None)
        if not tb_text and isinstance(error, BaseException) and error.__traceback__ is not None:
            import traceback as _tb

            try:
                tb_text = "".join(_tb.format_exception(type(error), error, error.__traceback__))
            except Exception:
                tb_text = None
        err_event = {
            "type": "node_error",
            "node_type": node_type,
            "node_index": index,
            # ``error`` is the canonical field (same as run meta / terminal
            # events); ``error_message`` kept for older consumers.
            "error": str(error),
            "error_message": str(error),
            "error_type": str(err_type),
            "level": "ERROR",
            "timestamp": self._timestamp(),
        }
        if tb_text:
            err_event["traceback"] = str(tb_text)[-20000:]
        plugin = getattr(error, "plugin_name", None)
        if plugin:
            err_event["plugin"] = str(plugin)
        if node_id:
            err_event["node_id"] = node_id
        self._emit_structured(err_event)

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
            "error": message,
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
