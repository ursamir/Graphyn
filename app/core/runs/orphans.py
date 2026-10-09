# app/core/runs/orphans.py
"""
Bounded Context:  Runs — ownership / crash recovery (DIST-ORPHAN-1)
Responsibility:   Know which process owns each in-flight run and fail runs whose
                  owner died (control-plane restart, OOM kill, host CLI crash)
                  with a clear ``orphaned_by_restart`` reason instead of leaving
                  them ``running`` forever.
Public Surface:   BOOT_ID, owner_stamp(), claim_run(run_id, run_dir),
                  release_run(run_id), owner_alive(run_dir, meta) -> (bool, why),
                  sweep_orphaned_runs(detected_by=...) -> dict,
                  start_orphan_sweeper() / stop_orphan_sweeper()
Rules:
  * Every RunManager stamps ``meta.owner`` and keeps ``<run>/.owner.json``
    fresh (heartbeat thread, GRAPHYN_RUN_HEARTBEAT_S, default 10 s) until the
    run is terminal. Mode A (in-process), Mode B (control plane orchestrating
    remote jobs) and host-CLI runs are all RunManagers, so all are covered.
  * An owner is dead when: same process boot → only if this process no longer
    holds the run; same host → its pid is gone or the pid now belongs to a
    different process start (container restart reuses pid 1/7); otherwise →
    heartbeat older than GRAPHYN_RUN_OWNER_STALE_S (default 60 s). Runs from
    before owner stamps (legacy) are orphans when they predate this process and
    no process heartbeats them.
  * Orphan → queued/claimed remote jobs of the run are cancelled (a still-busy
    worker's late completion is dropped with 409 run_cancelled — the job is not
    silently re-run on top of a dead orchestrator), meta → failed with
    error_type ``orphaned_by_restart``, a run-level ``error`` journal event,
    prove.json sealed, audit ``run.orphaned`` (error_code orphaned_by_restart).
  * Lost *worker* leases while the control plane is alive are a queue concern:
    idempotent jobs are requeued within the IR retry policy, others fail
    (app.core.distributed.queue._lease_loss_failure).
Must NOT:         Import app.api.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

OWNER_FILE = ".owner.json"
ORPHAN_REASON = "orphaned_by_restart"
SWEEP_STATUSES = frozenset({"pending", "queued", "running", "paused"})
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "completed", "skipped"})

BOOT_ID = uuid.uuid4().hex
_PROCESS_STARTED = datetime.now(timezone.utc)

_lock = threading.Lock()
_owned: dict[str, tuple[str, Any]] = {}  # run_id -> (run_dir, weakref | None)
_hb_thread: threading.Thread | None = None
_sweeper: threading.Thread | None = None
_sweeper_stop = threading.Event()


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def heartbeat_interval_s() -> float:
    return max(0.05, _env_float("GRAPHYN_RUN_HEARTBEAT_S", 10.0))


def owner_stale_s() -> float:
    return max(heartbeat_interval_s() * 2, _env_float("GRAPHYN_RUN_OWNER_STALE_S", 60.0))


def _proc_start(pid: int) -> str | None:
    """Kernel start time (clock ticks since boot) — distinguishes pid reuse."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            data = fh.read()
        return data.rsplit(")", 1)[1].split()[19]
    except Exception:
        return None


def _host() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def owner_stamp() -> dict[str, Any]:
    pid = os.getpid()
    return {
        "boot_id": BOOT_ID,
        "host": _host(),
        "pid": pid,
        "proc_start": _proc_start(pid),
        "process_started_at": _PROCESS_STARTED.isoformat(),
    }


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def claim_run(run_id: str, run_dir: str | os.PathLike[str], manager: Any = None) -> dict[str, Any]:
    """Record this process as the run's owner and keep it heartbeated."""
    stamp = owner_stamp()
    try:
        _write_json_atomic(Path(run_dir) / OWNER_FILE, {"run_id": run_id, **stamp})
    except OSError as exc:
        log.debug("owner stamp for %s not written: %s", run_id, exc)
    ref = None
    if manager is not None:
        try:
            ref = weakref.ref(manager)
        except TypeError:
            ref = None
    with _lock:
        _owned[str(run_id)] = (str(run_dir), ref)
    _ensure_heartbeat()
    return stamp


def release_run(run_id: str) -> None:
    with _lock:
        _owned.pop(str(run_id), None)


def owns_run(run_id: str) -> bool:
    with _lock:
        entry = _owned.get(str(run_id))
    if entry is None:
        return False
    _dir, ref = entry
    return ref is None or ref() is not None


def _read_status(run_dir: str) -> str:
    try:
        with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as fh:
            return str((json.load(fh) or {}).get("status") or "").lower()
    except Exception:
        return ""


def heartbeat_once() -> int:
    """Touch the owner file of every live run this process holds. Returns count."""
    with _lock:
        items = list(_owned.items())
    touched = 0
    for run_id, (run_dir, ref) in items:
        gone = ref is not None and ref() is None
        if gone or _read_status(run_dir) in TERMINAL:
            release_run(run_id)
            continue
        try:
            os.utime(os.path.join(run_dir, OWNER_FILE), None)
            touched += 1
        except FileNotFoundError:
            if not os.path.isdir(run_dir):  # run deleted
                release_run(run_id)
                continue
            claim_run(run_id, run_dir, ref() if ref is not None else None)
            touched += 1
        except OSError:
            pass
    return touched


def _ensure_heartbeat() -> None:
    global _hb_thread
    with _lock:
        if _hb_thread is not None and _hb_thread.is_alive():
            return

        def _loop() -> None:
            while True:
                time.sleep(heartbeat_interval_s())
                try:
                    heartbeat_once()
                except Exception:  # pragma: no cover - never kill the thread
                    log.debug("run owner heartbeat failed", exc_info=True)

        _hb_thread = threading.Thread(target=_loop, name="graphyn-run-heartbeat", daemon=True)
        _hb_thread.start()


# ── liveness ─────────────────────────────────────────────────────────────


def _parse_dt(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _load_owner(run_dir: Path, meta: dict[str, Any]) -> tuple[dict[str, Any] | None, float | None]:
    path = run_dir / OWNER_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = max(0.0, time.time() - path.stat().st_mtime)
        if isinstance(data, dict):
            return data, age
    except Exception:
        pass
    owner = meta.get("owner")
    return (owner if isinstance(owner, dict) else None), None


def owner_alive(run_dir: str | os.PathLike[str], meta: dict[str, Any]) -> tuple[bool, str]:
    """(alive, why) for the process recorded as owning this run."""
    run_dir = Path(run_dir)
    run_id = str(meta.get("run_id") or run_dir.name)
    if owns_run(run_id):
        return True, "owned by this process"
    owner, hb_age = _load_owner(run_dir, meta)
    if owner is None:
        try:
            from app.core.runs.run_control import get_active_run

            if get_active_run(run_id) is not None:
                return True, "active in this process"
        except Exception:
            pass
        created = _parse_dt(meta.get("created_at"))
        if created is not None and created >= _PROCESS_STARTED:
            return True, "created after this process started (no stamp yet)"
        return False, "no owner stamp (run predates owner tracking) and no live owner after restart"
    if owner.get("boot_id") == BOOT_ID:
        return False, "this process no longer runs it"
    pid = owner.get("pid")
    if owner.get("host") == _host() and isinstance(pid, int):
        start = _proc_start(pid)
        if start is None:
            return False, f"owner process {pid} on {owner.get('host')} is gone"
        if owner.get("proc_start") and start != str(owner.get("proc_start")):
            return False, f"owner process {pid} was restarted (pid reused by a new process)"
        if hb_age is not None and hb_age > owner_stale_s():
            return False, f"owner process {pid} stopped heartbeating {int(hb_age)}s ago"
        return True, f"owner process {pid} alive"
    if hb_age is not None and hb_age <= owner_stale_s():
        return True, f"owner {owner.get('host')}:{pid} heartbeat {int(hb_age)}s ago"
    if hb_age is None:
        created = _parse_dt(meta.get("created_at"))
        if created is not None and (datetime.now(timezone.utc) - created).total_seconds() <= owner_stale_s():
            return True, "just created"
        return False, f"owner {owner.get('host')}:{pid} has no heartbeat"
    return False, f"owner {owner.get('host')}:{pid} heartbeat stale ({int(hb_age)}s)"


# ── orphan handling ─────────────────────────────────────────────────────


def _cancel_run_jobs(run_id: str) -> list[str]:
    cancelled: list[str] = []
    try:
        from app.core.distributed.queue import get_job_queue

        queue = get_job_queue()
        if hasattr(queue, "active_job_ids_for_run"):
            job_ids = list(queue.active_job_ids_for_run(run_id))
        else:  # pragma: no cover - older queue shape
            job_ids = [j.job_id for j in queue.active_jobs() if str(getattr(j, "run_id", "")) == run_id]
        for job_id in job_ids:
            try:
                queue.cancel(job_id)
                cancelled.append(job_id)
            except KeyError:
                pass
    except Exception as exc:
        log.debug("orphan %s: job cancel skipped: %s", run_id, exc)
    return cancelled


def _append_event(run_dir: Path, event: dict[str, Any]) -> None:
    path = run_dir / "logs.json"
    try:
        events = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(events, list):
            events = []
    except Exception:
        events = []
    events.append(event)
    try:
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(events, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.debug("orphan event not journaled for %s: %s", run_dir.name, exc)


def mark_orphaned(run_dir: str | os.PathLike[str], meta: dict[str, Any], *, why: str, detected_by: str) -> bool:
    """Fail an orphaned run (compare-and-set on a non-terminal status)."""
    run_dir = Path(run_dir)
    run_id = str(meta.get("run_id") or run_dir.name)
    meta_path = run_dir / "meta.json"
    try:
        current = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        current = dict(meta)
    last_status = str(current.get("status") or "").lower()
    if last_status in TERMINAL:
        return False
    if (run_dir / "cancel_requested").exists():
        final_status, action = "cancelled", "cancelled (cancel was requested before the owner died)"
    else:
        final_status, action = "failed", "failed"
    cancelled_jobs = _cancel_run_jobs(run_id)
    now = datetime.now(timezone.utc)
    message = (
        f"{ORPHAN_REASON}: the process that owned this run stopped while it was {last_status or 'in flight'} "
        f"({why}). Nothing was re-run automatically"
        + (f"; {len(cancelled_jobs)} queued/claimed remote job(s) were cancelled" if cancelled_jobs else "")
        + ". Re-run the pipeline to retry — completed cacheable steps are reused."
    )
    owner, _ = _load_owner(run_dir, current)
    started = _parse_dt(current.get("started_at") or current.get("created_at"))
    current.update(
        {
            "run_id": run_id,
            "status": final_status,
            "error": message,
            "error_type": ORPHAN_REASON,
            "reason": ORPHAN_REASON,
            "orphaned_at": now.isoformat(),
            "orphan": {
                "detected_by": detected_by,
                "why": why,
                "previous_owner": owner,
                "last_status": last_status,
                "cancelled_jobs": cancelled_jobs,
                "detected_by_owner": owner_stamp(),
            },
        }
    )
    if started is not None and current.get("duration_s") is None:
        current["duration_s"] = round((now - started).total_seconds(), 3)
    try:
        st = run_dir.stat()
        _write_json_atomic(meta_path, current)
        os.utime(run_dir, (st.st_atime, st.st_mtime))
    except OSError as exc:
        log.warning("orphaned run %s could not be marked: %s", run_id, exc)
        return False
    _append_event(
        run_dir,
        {
            "timestamp": now.isoformat(),
            "level": "ERROR",
            "type": "error",
            "event": "run_orphaned",
            "error": message,
            "error_type": ORPHAN_REASON,
            "message": message,
            **({"node_id": current.get("current_node")} if current.get("current_node") else {}),
        },
    )
    try:
        from app.core.runs.run_control import deregister_active_run

        deregister_active_run(run_id)
    except Exception:
        pass
    try:
        from app.core.runs.audit_record import seal_run_record

        graph = None
        gp = run_dir / "graph.json"
        if gp.exists():
            try:
                graph = json.loads(gp.read_text(encoding="utf-8"))
            except Exception:
                graph = None
        seal_run_record(run_dir, run_id=run_id, status=final_status, meta=current,
                        graph=graph if isinstance(graph, dict) else None, artifacts=[])
    except Exception:
        log.debug("orphan prove seal skipped for %s", run_id, exc_info=True)
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor="system",
            action="run.orphaned",
            resource_type="run",
            resource_id=run_id,
            result="failure",
            actor_kind="system",
            error_code=ORPHAN_REASON,
            meta={
                "status": final_status,
                "why": why,
                "detected_by": detected_by,
                "last_status": last_status,
                "cancelled_jobs": cancelled_jobs,
                "started_by": current.get("actor"),
                "project": current.get("project"),
                "graph_name": current.get("graph_name"),
            },
        )
    except Exception:
        log.debug("orphan audit skipped for %s", run_id, exc_info=True)
    log.warning("run %s %s: %s (%s)", run_id, action, ORPHAN_REASON, why)
    return True


def sweep_orphaned_runs(*, detected_by: str = "sweep", runs_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Fail every in-flight run whose owner is dead. Never deletes anything."""
    if runs_root is None:
        from app.core.config import runs_dir

        runs_root = runs_dir()
    root = Path(runs_root)
    out: dict[str, Any] = {"examined": 0, "alive": 0, "orphaned": [], "detected_by": detected_by}
    if not root.is_dir():
        return out
    for entry in list(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        try:
            meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(meta, dict) or str(meta.get("status") or "").lower() not in SWEEP_STATUSES:
            continue
        out["examined"] += 1
        alive, why = owner_alive(entry, meta)
        if alive:
            out["alive"] += 1
            continue
        if mark_orphaned(entry, meta, why=why, detected_by=detected_by):
            out["orphaned"].append(str(meta.get("run_id") or entry.name))
    return out


def run_sweep_cycle(detected_by: str = "sweep") -> dict[str, Any]:
    """One reconcile pass: orphaned runs + expired worker leases."""
    result = sweep_orphaned_runs(detected_by=detected_by)
    try:
        from app.core.distributed.queue import get_job_queue

        result["requeued_jobs"] = get_job_queue().reclaim_expired_leases()
    except Exception as exc:
        log.debug("lease reclaim in orphan sweep failed: %s", exc)
    return result


def start_orphan_sweeper(interval_s: float | None = None) -> threading.Thread:
    """Startup pass now, then every GRAPHYN_ORPHAN_SWEEP_S (default 30 s)."""
    global _sweeper
    interval = interval_s if interval_s is not None else max(1.0, _env_float("GRAPHYN_ORPHAN_SWEEP_S", 30.0))
    _sweeper_stop.clear()

    def _loop() -> None:
        try:
            res = run_sweep_cycle("startup")
            log.info(
                "Startup orphan reconcile: examined=%s orphaned=%s requeued_jobs=%s",
                res.get("examined"), len(res.get("orphaned") or []), len(res.get("requeued_jobs") or []),
            )
        except Exception:
            log.warning("startup orphan reconcile failed", exc_info=True)
        while not _sweeper_stop.wait(interval):
            try:
                res = run_sweep_cycle("sweep")
                if res.get("orphaned") or res.get("requeued_jobs"):
                    log.info("Orphan sweep: orphaned=%s requeued_jobs=%s", res.get("orphaned"), res.get("requeued_jobs"))
            except Exception:
                log.debug("orphan sweep failed", exc_info=True)

    _sweeper = threading.Thread(target=_loop, name="graphyn-orphan-sweep", daemon=True)
    _sweeper.start()
    return _sweeper


def stop_orphan_sweeper(timeout: float = 2.0) -> None:
    _sweeper_stop.set()
    if _sweeper is not None:
        _sweeper.join(timeout=timeout)
