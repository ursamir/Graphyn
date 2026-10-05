# app/core/runs/run_journal.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Filesystem persistence for a single pipeline run. Manages
                  the run directory lifecycle, meta.json, resume state,
                  and artifact registration facade.
Owns:             RunManager class — run directory, meta.json, pause/cancel
                  threading events, artifact registration delegation.
                  Checkpoint discovery delegated to app.core.runs.checkpoint.
                  Every terminal transition (succeeded / failed / cancelled)
                  seals the hash-chained audit record (prove.json, via
                  app.core.runs.audit_record) and appends run.finish /
                  run.fail / run.cancel to the platform audit log.
Public Surface:   RunManager (constructor, save_*, mark_*, pause, resume,
                  cancel, poll_cancelled, durable_status, register_artifact, artifacts,
                  get_provenance_summary); write_cancel_marker, CANCEL_MARKER.
                  Status writes are compare-and-set via app.core.runs.run_status.
Must NOT:         Import from app.domain, app.api, or app.core.execution.orchestrator.
                  Must not understand pipeline execution order or node logic.
Dependencies:     BC6 (artifact_store, provenance, checkpoint, audit_record,
                  trust.audit), BC1 (ir.loader),
                  app.core.config, app.core.errors (ResumeError),
                  app.core.runs.run_status (transition matrix).
Reason To Change: Run persistence format evolves, resume state schema changes,
                  or artifact registration delegation changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.core.config import project_dir as _project_dir
from app.core.errors import ResumeError

log = logging.getLogger(__name__)


CANCEL_MARKER = "cancel_requested"


def write_cancel_marker(run_dir: str) -> None:
    """Create the durable cancel marker in ``run_dir`` (best-effort, idempotent).

    Unlike ``status`` in meta.json (read-modify-written by many writers), the
    marker is never rewritten, so a cancel from another process (API offline
    cancel of a queued run, Mode A multi-process) cannot be lost to a racing
    meta write. RunManager.is_cancelled and every status transition honour it.
    """
    try:
        path = os.path.join(run_dir, CANCEL_MARKER)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(datetime.now(timezone.utc).isoformat() + "\n")
    except Exception:
        log.debug("cancel marker write failed for %s", run_dir, exc_info=True)


class ArtifactCommitForbidden(RuntimeError):
    """Raised when a cancelled run attempts to commit an artifact (API-FORBID-005)."""


if TYPE_CHECKING:
    from app.core.artifacts.artifact_store import ArtifactRecord, ArtifactStore
    from app.core.artifacts.provenance import ProvenanceStore

# Patchable for test isolation
_WORKSPACE = str(_project_dir())


class RunManager:
    """Manages the lifecycle of a single pipeline run.

    Creates the run directory on construction and writes an initial meta.json
    so the run appears in history even if the pipeline fails before completion.
    """

    def __init__(self, base_dir: str | None = None) -> None:
        if base_dir is None:
            base_dir = str(_project_dir() / "runs")

        self.run_id = str(uuid.uuid4()).replace("-", "")
        self.base_path = os.path.join(base_dir, self.run_id)
        self._start_time = time.time()

        self._pause_event = threading.Event()
        self._pause_event.set()   # not paused initially
        self._cancel_event = threading.Event()
        self._meta_lock = threading.Lock()
        self._last_durable_cancel_probe = float("-inf")

        self._graph_hash: str = ""
        self._artifact_store: ArtifactStore | None = None
        self._provenance_store: ProvenanceStore | None = None
        self._artifacts: list[ArtifactRecord] = []
        self._artifacts_lock = threading.Lock()

        os.makedirs(self.base_path, exist_ok=True)
        # PERS-001 / SRS §13.2: durable pending before async run_id ack;
        # orchestrator calls mark_running() when execution actually starts.
        self._write_meta({
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        })

    # ── Meta persistence ───────────────────────────────────────────────────────

    def _write_meta(self, data: dict) -> None:
        # SA-RJ1 fix: write to a .tmp file then os.replace() for atomic rename
        # on POSIX — prevents corrupt meta.json if the process crashes mid-write.
        # SA-RJ2 fix: acquire _meta_lock here so ALL callers (__init__,
        # save_metadata, mark_failed, mark_cancelled) are automatically
        # thread-safe without each needing to acquire the lock themselves.
        path = os.path.join(self.base_path, "meta.json")
        tmp = path + ".tmp"
        with self._meta_lock:
            self._write_meta_unlocked(data, path, tmp)

    def _write_meta_unlocked(self, data: dict, path: str, tmp: str) -> None:
        """Write meta.json atomically. Caller MUST hold _meta_lock."""
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)  # atomic on POSIX

    def _read_meta_unlocked(self, meta_path: str) -> dict:
        """Read meta.json (caller holds _meta_lock); {} when missing/corrupt."""
        if not os.path.exists(meta_path):
            return {}
        try:
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _status_write_allowed(self, current_raw, action: str) -> bool:
        """Compare-and-set gate for status writes (run_status matrix).

        Terminal statuses (succeeded/failed/cancelled) are never overwritten
        except by transitions the matrix explicitly allows (cancel→cancelled
        idempotent ack). ``pause`` / ``resume`` / ``start`` follow the matrix
        strictly. ``succeed`` / ``fail`` / ``cancel`` from any non-terminal
        status are allowed (writers such as the distributed backend finalize
        straight from ``pending``). A durable cancel marker (cross-process
        cancel) blocks every transition except ``cancel``.
        """
        from app.core.runs.run_status import TERMINAL_STATUSES, can_transition, normalize_status

        current = normalize_status(current_raw) if current_raw else "pending"
        if action != "cancel" and self._cancel_marker_exists():
            return False
        if current in TERMINAL_STATUSES:
            return can_transition(current, action)
        if action in ("succeed", "fail", "cancel"):
            return True
        if action == "start":
            # pending → running; running → running idempotent; paused stays paused.
            return current in ("pending", "running", "unknown")
        if action == "pause":
            # Any active status may pause (a queued run pauses before its first node).
            return True
        if action == "resume":
            return current == "paused"
        return can_transition(current, action)

    def _transition_status(self, action: str, new_status: str) -> bool:
        """Atomically write ``status`` if the transition is legal. Returns success."""
        meta_path = os.path.join(self.base_path, "meta.json")
        tmp = meta_path + ".tmp"
        with self._meta_lock:
            existing = self._read_meta_unlocked(meta_path)
            if not self._status_write_allowed(existing.get("status"), action):
                log.debug(
                    "run %s: refusing status %s (action=%s) from %r",
                    self.run_id, new_status, action, existing.get("status"),
                )
                return False
            existing["status"] = new_status
            self._write_meta_unlocked(existing, meta_path, tmp)
            return True

    @property
    def durable_status(self) -> str | None:
        """Normalized status from meta.json (None when unreadable)."""
        from app.core.runs.run_status import normalize_status

        meta_path = os.path.join(self.base_path, "meta.json")
        with self._meta_lock:
            raw = self._read_meta_unlocked(meta_path).get("status")
        return normalize_status(raw) if isinstance(raw, str) else None

    def _cancel_marker_path(self) -> str:
        return os.path.join(self.base_path, CANCEL_MARKER)

    def _cancel_marker_exists(self) -> bool:
        try:
            return os.path.exists(self._cancel_marker_path())
        except Exception:
            return False

    def _write_meta_field(self, key: str, value) -> None:
        """Update a single field in meta.json without overwriting others (thread-safe).

        SA-RJ2: the entire read-modify-write is performed under _meta_lock to
        prevent a concurrent write from being lost between the read and the write.
        """
        meta_path = os.path.join(self.base_path, "meta.json")
        tmp = meta_path + ".tmp"
        with self._meta_lock:
            existing = {}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, encoding="utf-8") as f:
                        existing = json.load(f)
                except Exception:
                    pass
            existing[key] = value
            self._write_meta_unlocked(existing, meta_path, tmp)

    def save_config(self, config_yaml: str) -> None:
        path = os.path.join(self.base_path, "config.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(config_yaml)

    def save_logs(self, logs) -> None:
        path = os.path.join(self.base_path, "logs.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(list(logs), f, indent=2, default=str)

    def save_metadata(self, metadata: dict) -> bool:
        """Finalize a successful run (status → succeeded) — compare-and-set.

        If the run was cancelled (in-process event, durable cancel marker, or
        a terminal status already on disk) the metadata fields are still
        merged but the terminal status is preserved and no ``succeeded``
        notification / prove capture is emitted. Returns True when the run
        was recorded as succeeded.
        """
        if self.is_cancelled:
            self.mark_cancelled()
        duration = time.time() - self._start_time
        meta_path = os.path.join(self.base_path, "meta.json")
        tmp = meta_path + ".tmp"
        with self._meta_lock:
            existing = self._read_meta_unlocked(meta_path)
            allowed = self._status_write_allowed(existing.get("status"), "succeed")
            created = existing.get("created_at") or datetime.now(timezone.utc).isoformat()
            extra = {k: v for k, v in metadata.items() if k != "status"}
            full = {
                **existing,
                "run_id": self.run_id,
                "created_at": created,
                "duration_s": round(duration, 3),
                **extra,
            }
            if allowed:
                full["status"] = "succeeded"
            else:
                from app.core.runs.run_status import TERMINAL_STATUSES, normalize_status

                cur = normalize_status(existing.get("status"))
                full["status"] = cur if cur in TERMINAL_STATUSES else "cancelled"
            self._write_meta_unlocked(full, meta_path, tmp)
        if not allowed:
            log.info(
                "run %s: not marking succeeded — status is %r",
                self.run_id, full.get("status"),
            )
            return False
        self._seal_terminal("succeeded", full)
        try:
            from app.core.runs.run_notify import notify_run_terminal

            notify_run_terminal(
                "succeeded",
                self.run_id,
                graph_name=full.get("graph_name") if isinstance(full.get("graph_name"), str) else None,
                project=full.get("project") if isinstance(full.get("project"), str) else None,
            )
        except Exception:
            pass
        return True

    def _seal_terminal(self, status: str, meta: dict) -> None:
        """Seal prove.json (audit record v2, hash-chained) + audit run.finish/fail/cancel.

        Best-effort: never raises into the lifecycle caller. Only the first
        terminal transition seals (prove.json is first-writer-wins).
        """
        record = None
        try:
            from app.core.runs.audit_record import seal_run_record

            graph_data = None
            graph_path = os.path.join(self.base_path, "graph.json")
            if os.path.exists(graph_path):
                try:
                    with open(graph_path, encoding="utf-8") as gf:
                        graph_data = json.load(gf)
                except Exception:
                    graph_data = None
            m = dict(meta)
            if self._graph_hash and not m.get("graph_hash"):
                m["graph_hash"] = self._graph_hash
            record = seal_run_record(
                self.base_path,
                run_id=self.run_id,
                status=status,
                meta=m,
                graph=graph_data if isinstance(graph_data, dict) else None,
                artifacts=list(self.artifacts),
            )
        except Exception:
            log.debug("audit record seal failed for %s", self.run_id, exc_info=True)
        try:
            from app.core.trust.audit import record_audit

            action = {"succeeded": "run.finish", "failed": "run.fail", "cancelled": "run.cancel"}.get(status, "run.finish")
            record_audit(
                actor=str(meta.get("actor") or "system"),
                actor_verified=bool(meta.get("actor_verified")),
                claimed_actor=meta.get("claimed_actor") or None,
                action=action,
                resource_type="run",
                resource_id=self.run_id,
                result="failure" if status == "failed" else "success",
                meta={
                    "status": status,
                    "graph_name": meta.get("graph_name"),
                    "project": meta.get("project"),
                    "trigger": meta.get("trigger"),
                    "record_hash": (record or {}).get("record_hash"),
                    "error": meta.get("error") if status == "failed" else None,
                    "replay_of": meta.get("replay_of"),
                },
            )
        except Exception:
            log.debug("terminal audit event failed for %s", self.run_id, exc_info=True)

    def save_graph_ir(self, graph_data: dict, *, logical_hash: str | None = None) -> None:
        """Write graph.json and set self._graph_hash.

        ``graph_data`` is the *materialized* graph actually executed (e.g. with
        artifact paths scoped under ``runs/<run_id>/``). When ``logical_hash``
        is given it is the hash of the pre-scoping graph; it becomes the run's
        ``graph_hash`` (used for resume validation, the checkpoint index and
        provenance) because the materialized hash differs on every run.
        The materialized hash is kept as ``materialized_graph_hash``.
        """
        path = os.path.join(self.base_path, "graph.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(graph_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
        materialized = hashlib.sha256(
            json.dumps(graph_data, sort_keys=True).encode()
        ).hexdigest()
        self._graph_hash = logical_hash or materialized
        self._write_meta_field("graph_hash", self._graph_hash)
        if logical_hash and logical_hash != materialized:
            self._write_meta_field("materialized_graph_hash", materialized)

    def mark_failed(
        self,
        error: str,
        *,
        node_stats: list | None = None,
        failed_node_id: str | None = None,
        failed_node_type: str | None = None,
        error_type: str | None = None,
        error_traceback: str | None = None,
    ) -> bool:
        """Record a failure — compare-and-set; never overwrites a terminal status.

        Returns True when the run was recorded as failed (False when it was
        already succeeded/failed/cancelled — the first terminal status wins).
        """
        duration = time.time() - self._start_time
        meta_path = os.path.join(self.base_path, "meta.json")
        tmp = meta_path + ".tmp"
        with self._meta_lock:
            existing = self._read_meta_unlocked(meta_path)
            if not self._status_write_allowed(existing.get("status"), "fail"):
                log.debug(
                    "run %s: not marking failed (%s) — status is %r",
                    self.run_id, error, existing.get("status"),
                )
                return False
            stats = list(node_stats if node_stats is not None else existing.get("node_stats") or [])
            if failed_node_id and not any(s.get("node_id") == failed_node_id for s in stats):
                stats.append({
                    "node_id": failed_node_id,
                    "node_type": failed_node_type or "",
                    "status": "failed",
                })
            existing.update({
                "run_id": self.run_id,
                "duration_s": round(duration, 3),
                "status": "failed",
                "error": error,
            })
            if stats:
                existing["node_stats"] = stats
            if error_type:
                existing["error_type"] = str(error_type)
            if error_traceback:
                existing["error_traceback"] = str(error_traceback)[-20000:]
            if failed_node_id:
                existing["failed_node_id"] = failed_node_id
                if failed_node_type:
                    existing["failed_node_type"] = failed_node_type
            self._write_meta_unlocked(existing, meta_path, tmp)
        self._seal_terminal("failed", existing)
        try:
            from app.core.runs.run_notify import notify_run_terminal

            notify_run_terminal(
                "failed",
                self.run_id,
                error=error,
                graph_name=existing.get("graph_name") if isinstance(existing.get("graph_name"), str) else None,
                project=existing.get("project") if isinstance(existing.get("project"), str) else None,
            )
        except Exception:
            pass
        return True

    def mark_cancelled(self) -> bool:
        """Record cancellation — compare-and-set (never overwrites succeeded/failed)."""
        duration = time.time() - self._start_time
        meta_path = os.path.join(self.base_path, "meta.json")
        tmp = meta_path + ".tmp"
        with self._meta_lock:
            existing = self._read_meta_unlocked(meta_path)
            if not self._status_write_allowed(existing.get("status"), "cancel"):
                return False
            already_cancelled = str(existing.get("status") or "").lower() in ("cancelled", "canceled")
            existing.update({
                "status": "cancelled",
                "duration_s": round(duration, 3),
            })
            self._write_meta_unlocked(existing, meta_path, tmp)
        if already_cancelled:
            return True  # idempotent re-stamp — the cancel event already fired
        self._seal_terminal("cancelled", existing)
        try:
            from app.core.runs.run_notify import notify_run_terminal

            notify_run_terminal(
                "cancelled",
                self.run_id,
                graph_name=existing.get("graph_name") if isinstance(existing.get("graph_name"), str) else None,
                project=existing.get("project") if isinstance(existing.get("project"), str) else None,
            )
        except Exception:
            pass
        return True

    def mark_running(self) -> bool:
        """Transition durable meta pending→running (SRS §13.2) — compare-and-set.

        Refused (returns False) when the run is already terminal or a durable
        cancel was requested while the run was queued.
        """
        return self._transition_status("start", "running")

    # ── Runtime control ────────────────────────────────────────────────────────

    def pause(self) -> bool:
        """Pause after the current node — refused once the run is terminal."""
        if not self._transition_status("pause", "paused"):
            return False
        self._pause_event.clear()
        return True

    def resume(self) -> bool:
        """Resume a paused run — only legal from ``paused``."""
        self._pause_event.set()
        return self._transition_status("resume", "running")

    def cancel(self) -> None:
        self._cancel_event.set()
        self._pause_event.set()  # unblock if paused
        write_cancel_marker(self.base_path)

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    @property
    def is_cancelled(self) -> bool:
        """True after cancel() or a durable cancel (other process / queued cancel).

        The durable check (cancel marker file or ``status: cancelled`` in
        meta.json, written e.g. by the API for a run executing in another
        process) is throttled to one filesystem probe per 0.5 s because this
        property is polled from hot loops (retry back-off, subprocess wait).
        Use :meth:`poll_cancelled` at node boundaries for an unthrottled check.
        """
        if self._cancel_event.is_set():
            return True
        now = time.monotonic()
        if now - self._last_durable_cancel_probe < 0.5:
            return False
        return self.poll_cancelled()

    def poll_cancelled(self) -> bool:
        """Unthrottled cancel check (in-process event + durable marker/status)."""
        if self._cancel_event.is_set():
            return True
        self._last_durable_cancel_probe = time.monotonic()
        durable = self._cancel_marker_exists()
        if not durable:
            try:
                meta_path = os.path.join(self.base_path, "meta.json")
                with open(meta_path, encoding="utf-8") as fh:
                    durable = str(json.load(fh).get("status") or "").lower() == "cancelled"
            except Exception:
                durable = False
        if durable:
            self._cancel_event.set()
            self._pause_event.set()
        return durable

    def wait_if_paused(self) -> None:
        self._pause_event.wait()

    # ── Resume state ───────────────────────────────────────────────────────────

    def init_resume_state(self, graph_hash: str) -> None:
        state = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "completed_nodes": [],
            "graph_hash": graph_hash,
        }
        path = os.path.join(self.base_path, "resume_state.json")
        with self._meta_lock:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, path)

    def update_resume_state(self, node_id: str) -> None:
        path = os.path.join(self.base_path, "resume_state.json")
        with self._meta_lock:
            if not os.path.exists(path):
                # SA-RJ4 fix: warn instead of silently no-oping so callers can
                # detect that init_resume_state() was never called.
                log.warning(
                    "update_resume_state called for run '%s' but resume_state.json "
                    "does not exist — was init_resume_state() called?",
                    self.run_id,
                )
                return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except (json.JSONDecodeError, ValueError):
                log.warning("resume_state.json is corrupt for run %s — skipping update", self.run_id)
                return
            completed = state.get("completed_nodes", [])
            if node_id not in completed:
                completed.append(node_id)
            state["completed_nodes"] = completed
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, path)

    def load_resume_state(self, run_id: str) -> dict:
        """Load resume_state.json from a prior run. Raises ResumeError on failure."""
        from app.core.config import runs_dir as _runs_dir
        prior_run_path = os.path.join(str(_runs_dir()), run_id)
        if not os.path.exists(prior_run_path):
            raise ResumeError(f"Resume run '{run_id}' not found at {prior_run_path}")
        state_path = os.path.join(prior_run_path, "resume_state.json")
        if not os.path.exists(state_path):
            raise ResumeError(f"No resume_state.json found for run '{run_id}'")
        try:
            with open(state_path) as f:
                return json.load(f)
        except Exception as exc:
            raise ResumeError(
                f"Failed to parse resume_state.json for run '{run_id}': {exc}"
            ) from exc

    def find_latest_checkpoint(self, node_id: str) -> dict | None:
        """Search runs/ for the most recent checkpoint for node_id.

        Delegates to checkpoint.find_latest_checkpoint() — checkpoint
        discovery is a storage query that belongs in checkpoint.py, not
        in the run lifecycle manager (SA-RJ-ARCH fix).
        """
        from app.core.runs.checkpoint import find_latest_checkpoint  # noqa: PLC0415
        return find_latest_checkpoint(node_id, graph_hash=self._graph_hash or None)

    # ── Artifact registration ──────────────────────────────────────────────────

    @staticmethod
    def compute_graph_hash(graph_ir) -> str:
        from app.core.ir.loader import dump_ir
        return hashlib.sha256(
            json.dumps(dump_ir(graph_ir), sort_keys=True).encode()
        ).hexdigest()

    def _get_artifact_store(self) -> "ArtifactStore":
        if self._artifact_store is None:
            from app.core.artifacts.artifact_store import ArtifactStore
            self._artifact_store = ArtifactStore()
        return self._artifact_store

    def _get_provenance_store(self) -> "ProvenanceStore":
        if self._provenance_store is None:
            from app.core.artifacts.provenance import ProvenanceStore
            self._provenance_store = ProvenanceStore()
        return self._provenance_store

    def register_artifact(
        self,
        node_id: str,
        node_type: str,
        artifact_type: str,
        data,
        metadata: dict | None = None,
        input_artifact_ids: list[str] | None = None,
        name: str | None = None,
    ) -> "ArtifactRecord":
        from app.core.artifacts.artifact_store import ArtifactRecord

        # API-FORBID-005 / RT-CANCEL: hard-forbid artifact commit after cancel.
        if self.is_cancelled:
            raise ArtifactCommitForbidden(
                f"Cannot commit artifact for cancelled run {self.run_id}"
            )
        # Also refuse when durable meta already terminal cancelled (race).
        try:
            meta_path = os.path.join(self.base_path, "meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if isinstance(meta, dict) and str(meta.get("status") or "").lower() == "cancelled":
                    raise ArtifactCommitForbidden(
                        f"Cannot commit artifact for cancelled run {self.run_id}"
                    )
        except ArtifactCommitForbidden:
            raise
        except Exception:
            pass

        record, deduplicated = self._get_artifact_store().register(
            run_id=self.run_id,
            node_id=node_id,
            node_type=node_type,
            artifact_type=artifact_type,
            data=data,
            metadata=metadata,
            # SA-RJ5 fix: forward name so by_name index is populated when a
            # caller provides a name (previously always passed name=None).
            name=name,
        )

        _input_ids = input_artifact_ids or []
        # Always record provenance, even when `deduplicated` — otherwise this
        # run's own by_run provenance index stays permanently empty whenever
        # its output happens to content-match an earlier run (deterministic/
        # seeded pipelines hit this constantly). provenance.record() no longer
        # overwrites another run's canonical record in that case; it only adds
        # this run to the artifact's by_run index (see provenance.py).
        if record.artifact_id not in _input_ids:
            try:
                self._get_provenance_store().record(
                    artifact_id=record.artifact_id,
                    run_id=self.run_id,
                    node_id=node_id,
                    node_type=node_type,
                    graph_hash=self._graph_hash,
                    input_artifact_ids=_input_ids,
                )
            except Exception as exc:
                log.warning(
                    "Failed to record provenance for artifact %s: %s",
                    record.artifact_id,
                    exc,
                )

        with self._artifacts_lock:
            self._artifacts.append(record)
        try:
            from pathlib import Path as _Path

            from app.core.runs.outputs_index import append_artifact_source

            append_artifact_source(_Path(self.base_path), record)
        except Exception as exc:
            log.debug("outputs_index append failed for %s: %s", record.artifact_id, exc)
        return record

    @property
    def artifacts(self) -> list["ArtifactRecord"]:
        with self._artifacts_lock:
            return list(self._artifacts)

    def get_provenance_summary(self) -> dict:
        artifacts_list = [r.model_dump(mode="json") for r in self.artifacts]
        provenance_list: list[dict] = []
        if self._provenance_store is not None:
            try:
                records = self._provenance_store.find_by_run(self.run_id)
                provenance_list = [r.model_dump(mode="json") for r in records]
            except Exception:
                provenance_list = []
        return {
            "run_id": self.run_id,
            "graph_hash": self._graph_hash,
            "artifacts": artifacts_list,
            "provenance_records": provenance_list,
        }
