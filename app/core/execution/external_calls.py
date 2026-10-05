# app/core/execution/external_calls.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Drain the ``Node.record_external_call`` side-channel after a
                  node executes and persist the accumulated rows into run meta
                  ``external_calls`` (read by the sealed audit record, G6).
Owns:             drain_external_calls()
Public Surface:   drain_external_calls
Must NOT:         Import app.domain, app.api or the orchestrator; raise into the
                  executor (best-effort, like publish_files registration).
Dependencies:     stdlib (logging, threading).
Reason To Change: External-call audit row shape or persistence target changes.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger(__name__)

_lock = threading.Lock()
_RUN_ATTR = "_graphyn_external_calls"
META_FIELD = "external_calls"


def drain_external_calls(run: Any, node: Any, node_id: str, node_type: str) -> list[dict[str, Any]]:
    """Drain *node*'s queued external calls and append them to *run* meta.

    Call once per node execution — on success AND on failure (calls made
    before an exception are still egress that happened). Returns the rows
    (annotated with ``node_id`` / ``node_type``) drained this time.
    Never raises.
    """
    try:
        take = getattr(node, "take_external_calls", None)
        calls = take() if callable(take) else []
    except Exception:
        log.debug("take_external_calls failed for %s", node_id, exc_info=True)
        return []
    if not calls:
        return []
    rows = [{**c, "node_id": node_id, "node_type": node_type} for c in calls if isinstance(c, dict)]
    if run is None or not rows:
        return rows
    with _lock:
        acc = getattr(run, _RUN_ATTR, None)
        if not isinstance(acc, list):
            acc = []
            try:
                setattr(run, _RUN_ATTR, acc)
            except Exception:
                pass
        acc.extend(rows)
        snapshot = list(acc)
    writer = getattr(run, "_write_meta_field", None)
    if callable(writer):
        try:
            writer(META_FIELD, snapshot)
        except Exception:
            log.debug("external_calls meta write failed for %s", node_id, exc_info=True)
    return rows
