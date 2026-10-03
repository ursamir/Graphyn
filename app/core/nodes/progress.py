# app/core/nodes/progress.py
"""
Bounded Context:  BC2 — Node Contract (progress side-channel)
Responsibility:   Let a running node report live progress (epoch, loss,
                  accuracy, pct …) without knowing how it is executed.
Owns:             emit_node_progress(); the per-run progress context
                  (contextvar: node_id, node_type, sink); the isolated
                  worker stderr marker protocol (``@@GRAPHYN_PROGRESS@@ <json>``);
                  per-node throttling (≤ 2 events / s); human message text.
Public Surface:   emit_node_progress(payload), progress_context(...),
                  current_progress_sink(), parse_progress_line(line),
                  format_progress_message(node_type, payload),
                  build_progress_event(node_id, node_type, payload),
                  ProgressThrottle, PROGRESS_MARKER, PROGRESS_ENV_MARKER,
                  PROGRESS_ENV_FD.
Must NOT:         Import app.domain, app.api or any execution module; raise
                  into the caller (progress is best-effort, never fatal).
Dependencies:     stdlib (contextvars, json, os, sys, threading, time, datetime).
Reason To Change: The progress payload contract or the worker marker
                  protocol changes.

Contract (shared with plugins)
------------------------------
``emit_node_progress({"phase": "train", "epoch": 3, "epochs": 30,
"loss": 0.41, "accuracy": 0.82, "val_loss": 0.5, "val_accuracy": 0.78,
"pct": 10})``

* In-process (node executor set the context): a structured
  ``{"type": "node_progress", "node_id", "node_type", "ts", "timestamp",
  "level": "INFO", "message", **payload}`` event goes to the run journal
  (``logs.json``) and the NDJSON stream of ``POST /pipelines/run``.
* Isolated subprocess (no context, but ``GRAPHYN_PROGRESS_MARKER=1`` or
  ``GRAPHYN_PROGRESS_FD`` set by the host): one stderr line
  ``@@GRAPHYN_PROGRESS@@ <json>`` which the host isolated executor parses
  live and forwards as the same ``node_progress`` event.
* Anywhere else: no-op.
* Throttled to ≤ 2 events per second per node. A payload with
  ``"final": true`` or ``pct >= 100`` bypasses the throttle.
"""
from __future__ import annotations

import contextvars
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

PROGRESS_MARKER = "@@GRAPHYN_PROGRESS@@"
PROGRESS_ENV_MARKER = "GRAPHYN_PROGRESS_MARKER"
PROGRESS_ENV_FD = "GRAPHYN_PROGRESS_FD"
# Minimum seconds between two forwarded events of the same node (≤ 2/s).
MIN_INTERVAL_S = 0.5

ProgressSink = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class _ProgressContext:
    node_id: str
    node_type: str
    sink: ProgressSink


_CTX: contextvars.ContextVar[_ProgressContext | None] = contextvars.ContextVar(
    "graphyn_node_progress", default=None
)


class ProgressThrottle:
    """Thread-safe per-key rate limiter (default ≤ 2 events/s)."""

    def __init__(self, min_interval_s: float = MIN_INTERVAL_S) -> None:
        self._min = float(min_interval_s)
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, payload: dict[str, Any] | None = None) -> bool:
        if _bypasses_throttle(payload):
            with self._lock:
                self._last[key] = time.monotonic()
            return True
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self._min:
                return False
            self._last[key] = now
            return True


def _bypasses_throttle(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("final") is True:
        return True
    pct = payload.get("pct")
    try:
        return pct is not None and float(pct) >= 100.0
    except (TypeError, ValueError):
        return False


_THROTTLE = ProgressThrottle()


def _fmt_num(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}" if abs(value) >= 0.01 or value == 0 else f"{value:.3g}"
    return str(value)


def _humanize_type(node_type: str) -> str:
    text = str(node_type or "node").replace("Isolated_", "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "Node"


def format_progress_message(node_type: str, payload: dict[str, Any]) -> str:
    """Pretty one-liner, e.g. ``Trainer · epoch 3/30 · loss 0.41 · val_acc 0.78``."""
    parts = [_humanize_type(node_type)]
    p = payload if isinstance(payload, dict) else {}
    phase = p.get("phase")
    epoch, epochs = p.get("epoch"), p.get("epochs")
    if epoch is not None:
        parts.append(f"epoch {epoch}/{epochs}" if epochs is not None else f"epoch {epoch}")
    elif phase:
        parts.append(str(phase))
    done, total = p.get("done"), p.get("total")
    if done is not None and total is not None:
        parts.append(f"{done}/{total}")
    step, steps = p.get("step"), p.get("steps")
    if step is not None:
        parts.append(f"step {step}/{steps}" if steps is not None else f"step {step}")
    for key, label in (
        ("loss", "loss"),
        ("accuracy", "acc"),
        ("val_loss", "val_loss"),
        ("val_accuracy", "val_acc"),
    ):
        if p.get(key) is not None:
            parts.append(f"{label} {_fmt_num(p[key])}")
    if epoch is None and p.get("pct") is not None:
        parts.append(f"{_fmt_num(p['pct'])}%")
    msg = p.get("message")
    if isinstance(msg, str) and msg.strip() and len(parts) == 1:
        parts.append(msg.strip())
    return " · ".join(parts)


def _jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop / coerce values that json cannot encode (numpy scalars → float)."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None or isinstance(value, (str, bool, int, float)):
            out[str(key)] = value
            continue
        try:
            if hasattr(value, "item"):
                out[str(key)] = value.item()
                continue
        except Exception:
            pass
        try:
            json.dumps(value)
            out[str(key)] = value
        except (TypeError, ValueError):
            out[str(key)] = str(value)
    return out


_RESERVED = frozenset({"type", "node_id", "node_type", "ts", "timestamp", "level"})


def build_progress_event(node_id: str, node_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return the structured ``node_progress`` event for *payload*."""
    body = _jsonable({k: v for k, v in (payload or {}).items() if k not in _RESERVED})
    ts = datetime.now(timezone.utc).isoformat()
    event: dict[str, Any] = {
        "type": "node_progress",
        "node_id": str(node_id or ""),
        "node_type": str(node_type or ""),
        "ts": ts,
        "timestamp": ts,
        "level": "INFO",
        **body,
    }
    # Keep a plugin-provided message only when it is the pretty text; the
    # journal always gets a human line.
    event["message"] = format_progress_message(node_type, body)
    if isinstance(body.get("message"), str) and body["message"].strip():
        event["detail"] = body["message"].strip()
    return event


@contextmanager
def progress_context(node_id: str, node_type: str, sink: ProgressSink | None) -> Iterator[None]:
    """Bind the progress sink for the node running in this context/thread."""
    if sink is None:
        yield
        return
    token = _CTX.set(_ProgressContext(str(node_id or ""), str(node_type or ""), sink))
    try:
        yield
    finally:
        _CTX.reset(token)


def current_progress_sink() -> Callable[[dict[str, Any]], None] | None:
    """Return a callable forwarding raw payloads for the current node, or None.

    Captured by the isolated executor in the calling thread so its stderr
    reader thread can forward worker progress lines.
    """
    ctx = _CTX.get()
    if ctx is None:
        return None

    def _forward(payload: dict[str, Any]) -> None:
        _deliver(ctx, payload)

    return _forward


def _deliver(ctx: _ProgressContext, payload: dict[str, Any]) -> None:
    key = ctx.node_id or ctx.node_type
    if not _THROTTLE.allow(key, payload):
        return
    try:
        ctx.sink(build_progress_event(ctx.node_id, ctx.node_type, payload))
    except Exception:
        pass


def _marker_mode() -> bool:
    if os.environ.get(PROGRESS_ENV_MARKER, "").strip().lower() in ("1", "true", "yes"):
        return True
    return bool(os.environ.get(PROGRESS_ENV_FD, "").strip())


_WORKER_THROTTLE = ProgressThrottle()


def _write_marker(payload: dict[str, Any]) -> None:
    if not _WORKER_THROTTLE.allow("worker", payload):
        return
    try:
        line = f"{PROGRESS_MARKER} {json.dumps(_jsonable(payload), separators=(',', ':'))}\n"
    except Exception:
        return
    fd_raw = os.environ.get(PROGRESS_ENV_FD, "").strip()
    try:
        if fd_raw.isdigit() and int(fd_raw) not in (1, 2):
            os.write(int(fd_raw), line.encode("utf-8"))
            return
        sys.stderr.write(line)
        sys.stderr.flush()
    except Exception:
        pass


def emit_node_progress(payload: dict) -> None:
    """Report node progress; never raises, no-op outside a run.

    See the module docstring for the payload contract.
    """
    if not isinstance(payload, dict):
        return
    try:
        ctx = _CTX.get()
        if ctx is not None:
            _deliver(ctx, payload)
            return
        if _marker_mode():
            _write_marker(payload)
    except Exception:
        pass


def parse_progress_line(line: str) -> dict[str, Any] | None:
    """Return the payload of a ``@@GRAPHYN_PROGRESS@@ <json>`` line, else None."""
    if not isinstance(line, str):
        return None
    text = line.strip()
    if not text.startswith(PROGRESS_MARKER):
        return None
    raw = text[len(PROGRESS_MARKER):].strip()
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


__all__ = [
    "MIN_INTERVAL_S",
    "PROGRESS_ENV_FD",
    "PROGRESS_ENV_MARKER",
    "PROGRESS_MARKER",
    "ProgressThrottle",
    "build_progress_event",
    "current_progress_sink",
    "emit_node_progress",
    "format_progress_message",
    "parse_progress_line",
    "progress_context",
]
