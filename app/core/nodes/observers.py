# app/core/nodes/observers.py
"""
Bounded Context:  BC2 — Node Contract
Responsibility:   Define the observer interface and concrete implementations
                  for node lifecycle event callbacks.
Owns:             NodeObserver (ABC), LoggingObserver, CompositeObserver.
Public Surface:   NodeObserver, LoggingObserver, CompositeObserver.
Must NOT:         Import from app.domain, app.api, or any BC3/BC4/BC5/BC6 module.
Dependencies:     stdlib (abc, json, logging, traceback).
Reason To Change: New lifecycle events are added to the node protocol, or
                  new built-in observer implementations are needed.
"""
from __future__ import annotations

import json
import logging
import traceback as _traceback
from abc import ABC, abstractmethod
from typing import Any


class NodeObserver(ABC):
    """Abstract interface for node execution event callbacks.

    Implementations receive structured events at each lifecycle stage:
    - ``on_node_start``: immediately before ``process()`` is invoked
    - ``on_node_end``: after ``process()`` returns successfully
    - ``on_node_error``: when ``process()`` raises an exception
    """

    @abstractmethod
    def on_node_start(self, node_type: str, run_id: str) -> None:
        """Called immediately before process() is invoked.

        Args:
            node_type: The class name of the node being executed.
            run_id: The pipeline run identifier.
        """

    @abstractmethod
    def on_node_end(
        self,
        node_type: str,
        run_id: str,
        duration_s: float,
        input_counts: dict[str, int],
        output_counts: dict[str, int],
    ) -> None:
        """Called after process() returns successfully.

        Args:
            node_type: The class name of the node.
            run_id: The pipeline run identifier.
            duration_s: Wall-clock seconds spent in process().
            input_counts: Mapping of input port name → item count.
            output_counts: Mapping of output port name → item count.
        """

    @abstractmethod
    def on_node_error(
        self,
        node_type: str,
        run_id: str,
        exc: Exception,
    ) -> None:
        """Called when process() raises an exception.

        Args:
            node_type: The class name of the node.
            run_id: The pipeline run identifier.
            exc: The exception that was raised.
        """


class LoggingObserver(NodeObserver):
    """Writes one structured JSON line per event to a Python logger.

    Each event is serialised as a JSON object and emitted at the
    appropriate log level:

    - ``on_node_start`` → ``INFO``  ``{"event": "node_start", ...}``
    - ``on_node_end``   → ``INFO``  ``{"event": "node_end", ..., "duration_s": ..., ...}``
    - ``on_node_error`` → ``ERROR`` ``{"event": "node_error", ..., "error": ..., "error_type": ...}``
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger("node_observer")

    def on_node_start(self, node_type: str, run_id: str) -> None:
        self._log.info(json.dumps({
            "event": "node_start",
            "node_type": node_type,
            "run_id": run_id,
        }))

    def on_node_end(
        self,
        node_type: str,
        run_id: str,
        duration_s: float,
        input_counts: dict[str, int],
        output_counts: dict[str, int],
    ) -> None:
        self._log.info(json.dumps({
            "event": "node_end",
            "node_type": node_type,
            "run_id": run_id,
            "duration_s": duration_s,
            "input_counts": input_counts,
            "output_counts": output_counts,
        }))

    def on_node_error(self, node_type: str, run_id: str, exc: Exception) -> None:
        self._log.error(json.dumps({
            "event": "node_error",
            "node_type": node_type,
            "run_id": run_id,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "traceback": _traceback.format_exc(),
        }))


class CompositeObserver(NodeObserver):
    """Fans out all events to a list of child NodeObserver instances.

    Each child observer is called inside a try/except so that a failing
    observer does not prevent the remaining observers from receiving the
    event (N-15 fix).

    Example::

        composite = CompositeObserver([
            LoggingObserver(logging.getLogger("pipeline")),
            MetricsObserver(),
        ])
        node = CleanNode(config={}, seed=0, observer=composite)
    """

    def __init__(self, observers: list[NodeObserver]) -> None:
        self._observers = list(observers)
        self._log = logging.getLogger(__name__)

    def on_node_start(self, node_type: str, run_id: str) -> None:
        for obs in self._observers:
            try:
                obs.on_node_start(node_type, run_id)
            except Exception:
                self._log.warning(
                    "CompositeObserver: %r raised in on_node_start for node '%s'",
                    obs, node_type, exc_info=True,
                )

    def on_node_end(
        self,
        node_type: str,
        run_id: str,
        duration_s: float,
        input_counts: dict[str, int],
        output_counts: dict[str, int],
    ) -> None:
        for obs in self._observers:
            try:
                obs.on_node_end(node_type, run_id, duration_s, input_counts, output_counts)
            except Exception:
                self._log.warning(
                    "CompositeObserver: %r raised in on_node_end for node '%s'",
                    obs, node_type, exc_info=True,
                )

    def on_node_error(self, node_type: str, run_id: str, exc: Exception) -> None:
        for obs in self._observers:
            try:
                obs.on_node_error(node_type, run_id, exc)
            except Exception:
                self._log.warning(
                    "CompositeObserver: %r raised in on_node_error for node '%s'",
                    obs, node_type, exc_info=True,
                )
