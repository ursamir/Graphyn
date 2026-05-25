# app/core/run_control.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Active run registry. Maps run_id → RunManager for
                  pause/resume/cancel signal delivery.
Owns:             Backend selection (in-process dict or Redis pub/sub),
                  register/get/deregister public interface.
Public Surface:   register_active_run(run), get_active_run(run_id),
                  deregister_active_run(run_id)
Must NOT:         Import from app.domain, app.api, or any execution module.
                  Must not understand pipeline execution order.
Dependencies:     stdlib (threading), app.core.config (redis_url).
                  redis-py is an optional runtime dependency — absent when
                  GRAPHYN_REDIS_URL is not set.
Scalability Note: When GRAPHYN_REDIS_URL is set, run registrations are stored
                  in Redis so that any worker in a multi-worker deployment can
                  route pause/resume/cancel to the correct process via a
                  Redis pub/sub control channel (run:{run_id}:control).
                  When GRAPHYN_REDIS_URL is empty (default), the in-process
                  dict backend is used — identical behaviour to the previous
                  single-dict implementation.
Reason To Change: Active run registry backend changes, or run lifecycle
                  events are added.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # RunManager referenced only via string annotations below

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process fallback backend (used when GRAPHYN_REDIS_URL is not set)
# ---------------------------------------------------------------------------

_ACTIVE_RUNS: dict[str, "RunManager"] = {}  # type: ignore[name-defined]
_ACTIVE_RUNS_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Redis backend helpers
# ---------------------------------------------------------------------------

def _get_redis_client():
    """Return a connected redis.Redis client, or None if redis-py is absent
    or GRAPHYN_REDIS_URL is not configured.

    The client is created fresh on each call — callers that need connection
    pooling should cache the result themselves.  For the run-control use case
    (low-frequency pause/resume/cancel signals) a fresh client per call is
    acceptable.
    """
    from app.core.config import redis_url as _redis_url  # noqa: PLC0415

    url = _redis_url()
    if not url:
        return None

    try:
        import redis  # type: ignore[import]  # noqa: PLC0415
        return redis.Redis.from_url(url, decode_responses=True, socket_timeout=2.0)
    except ImportError:
        log.warning(
            "run_control: GRAPHYN_REDIS_URL is set but the 'redis' package is not "
            "installed. Falling back to in-process store. "
            "Install it with: pip install redis"
        )
        return None
    except Exception as exc:
        log.warning(
            "run_control: failed to connect to Redis at %r: %s. "
            "Falling back to in-process store.",
            url,
            exc,
        )
        return None


def _redis_key(run_id: str) -> str:
    """Return the Redis key used to mark a run as active."""
    return f"graphyn:active_run:{run_id}"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def register_active_run(run: "RunManager") -> None:  # type: ignore[name-defined]
    """Register a RunManager as the active run for its run_id.

    In Redis mode: writes a marker key ``graphyn:active_run:{run_id}`` with a
    TTL of 24 hours (safety net — deregister_active_run removes it explicitly).
    The RunManager object itself is always stored in the in-process dict so
    that pause/resume/cancel signals can be delivered to the correct object
    within this worker process.

    In in-process mode: stores the RunManager in ``_ACTIVE_RUNS`` only.
    """
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS[run.run_id] = run

    client = _get_redis_client()
    if client is not None:
        try:
            client.set(_redis_key(run.run_id), "1", ex=86400)  # 24-hour TTL
        except Exception as exc:
            log.warning(
                "run_control: failed to register run %r in Redis: %s",
                run.run_id,
                exc,
            )


def get_active_run(run_id: str) -> "RunManager | None":  # type: ignore[name-defined]
    """Return the active RunManager for run_id, or None if not active.

    In Redis mode: checks the in-process dict first (fast path — the run is
    on this worker).  If absent, checks Redis to distinguish "run is active on
    another worker" from "run does not exist / has completed".  Returns None
    in both cases — the caller cannot route to another worker from here.

    In in-process mode: returns from ``_ACTIVE_RUNS`` directly.

    SA-RC2: Returns None in all of these cases:
      - The run never existed in this process
      - The run has already completed and been deregistered
      - The run is executing on a different worker (SCALE-1)
    The caller cannot distinguish between these cases from the return value
    alone.
    """
    with _ACTIVE_RUNS_LOCK:
        run = _ACTIVE_RUNS.get(run_id)

    if run is not None:
        return run

    # Redis mode: log a debug note when the run is active on another worker
    client = _get_redis_client()
    if client is not None:
        try:
            exists = client.exists(_redis_key(run_id))
            if exists:
                log.debug(
                    "run_control: run %r is active on another worker — "
                    "cannot deliver control signal from this process.",
                    run_id,
                )
        except Exception as exc:
            log.debug("run_control: Redis exists check failed for %r: %s", run_id, exc)

    return None


def deregister_active_run(run_id: str) -> None:
    """Remove a run from the active registry (called in finally block).

    Removes from both the in-process dict and Redis (if configured).
    """
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS.pop(run_id, None)

    client = _get_redis_client()
    if client is not None:
        try:
            client.delete(_redis_key(run_id))
        except Exception as exc:
            log.warning(
                "run_control: failed to deregister run %r from Redis: %s",
                run_id,
                exc,
            )
