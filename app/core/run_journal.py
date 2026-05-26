# app/core/run_journal.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Filesystem persistence for a single pipeline run. Manages
                  the run directory lifecycle, meta.json, resume state,
                  and artifact registration facade.
Owns:             RunManager class — run directory, meta.json, pause/cancel
                  threading events, artifact registration delegation.
                  Checkpoint discovery delegated to app.core.checkpoint.
Public Surface:   RunManager (constructor, save_*, mark_*, pause, resume,
                  cancel, register_artifact, artifacts, get_provenance_summary)
Must NOT:         Import from app.domain, app.api, or app.core.orchestrator.
                  Must not understand pipeline execution order or node logic.
Dependencies:     BC6 (artifact_store, provenance, checkpoint), BC1 (ir.loader),
                  app.core.config, app.core.errors (ResumeError).
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

if TYPE_CHECKING:
    from app.core.artifact_store import ArtifactRecord, ArtifactStore
    from app.core.provenance import ProvenanceStore

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

        self.run_id = str(uuid.uuid4()).replace("-", "")[:16]
        self.base_path = os.path.join(base_dir, self.run_id)
        self._start_time = time.time()

        self._pause_event = threading.Event()
        self._pause_event.set()   # not paused initially
        self._cancel_event = threading.Event()
        self._meta_lock = threading.Lock()

        self._graph_hash: str = ""
        self._artifact_store: ArtifactStore | None = None
        self._provenance_store: ProvenanceStore | None = None
        self._artifacts: list[ArtifactRecord] = []
        self._artifacts_lock = threading.Lock()

        os.makedirs(self.base_path, exist_ok=True)
        self._write_meta({
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
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

    def _write_meta_field(self, key: str, value: str) -> None:
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
            json.dump(list(logs), f, indent=2)

    def save_metadata(self, metadata: dict) -> None:
        duration = time.time() - self._start_time
        full = {
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(duration, 3),
            "status": "completed",
            **metadata,
        }
        self._write_meta(full)

    def save_graph_ir(self, graph_data: dict) -> None:
        """Write graph.json and compute self._graph_hash."""
        path = os.path.join(self.base_path, "graph.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(graph_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        self._graph_hash = hashlib.sha256(
            json.dumps(graph_data, sort_keys=True).encode()
        ).hexdigest()

    def mark_failed(self, error: str) -> None:
        duration = time.time() - self._start_time
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
            existing.update({
                "run_id": self.run_id,
                "duration_s": round(duration, 3),
                "status": "failed",
                "error": error,
            })
            self._write_meta_unlocked(existing, meta_path, tmp)

    def mark_cancelled(self) -> None:
        duration = time.time() - self._start_time
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
            existing.update({
                "status": "cancelled",
                "duration_s": round(duration, 3),
            })
            self._write_meta_unlocked(existing, meta_path, tmp)

    # ── Runtime control ────────────────────────────────────────────────────────

    def pause(self) -> None:
        self._pause_event.clear()
        self._write_meta_field("status", "paused")

    def resume(self) -> None:
        self._pause_event.set()
        self._write_meta_field("status", "running")

    def cancel(self) -> None:
        self._cancel_event.set()
        self._pause_event.set()  # unblock if paused

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

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
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

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
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)

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

        Delegates to checkpoint._find_latest_checkpoint() — checkpoint
        discovery is a storage query that belongs in checkpoint.py, not
        in the run lifecycle manager (SA-RJ-ARCH fix).
        """
        from app.core.checkpoint import _find_latest_checkpoint  # noqa: PLC0415
        return _find_latest_checkpoint(node_id)

    # ── Artifact registration ──────────────────────────────────────────────────

    @staticmethod
    def compute_graph_hash(graph_ir) -> str:
        from app.core.ir.loader import dump_ir
        return hashlib.sha256(
            json.dumps(dump_ir(graph_ir), sort_keys=True).encode()
        ).hexdigest()

    def _get_artifact_store(self) -> "ArtifactStore":
        if self._artifact_store is None:
            from app.core.artifact_store import ArtifactStore
            self._artifact_store = ArtifactStore()
        return self._artifact_store

    def _get_provenance_store(self) -> "ProvenanceStore":
        if self._provenance_store is None:
            from app.core.provenance import ProvenanceStore
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
        from app.core.artifact_store import ArtifactRecord

        record: ArtifactRecord = self._get_artifact_store().register(
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
        if record.artifact_id not in _input_ids:
            self._get_provenance_store().record(
                artifact_id=record.artifact_id,
                run_id=self.run_id,
                node_id=node_id,
                node_type=node_type,
                graph_hash=self._graph_hash,
                input_artifact_ids=_input_ids,
            )

        with self._artifacts_lock:
            self._artifacts.append(record)
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
