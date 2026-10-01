# app/core/runs/outputs_index.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Run-level cache of ArtifactStore records for output listing.
                  Built only from ArtifactRecords — never rediscovers files by
                  walking trees or sniffing domain inventories (labels.csv, …).
Owns:             outputs_index.json schema, build/load/save/append helpers.
Public Surface:   INDEX_NAME, load_outputs_index, save_outputs_index,
                  build_outputs_index, append_artifact_source,
                  ensure_outputs_index, artifacts_from_index.
Must NOT:         Import app.domain. Must not parse labels.csv / assume WAV
                  layouts. Must not walk graph config output_dir trees.
Dependencies:     stdlib, app.core.artifacts.artifact_store (list only).
Reason To Change: Cache schema evolves, or listing stops needing a disk cache.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INDEX_NAME = "outputs_index.json"
INDEX_SCHEMA = 2

_INDEX_LOCK = threading.RLock()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def load_outputs_index(run_dir: Path) -> dict[str, Any] | None:
    path = Path(run_dir) / INDEX_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("outputs_index: corrupt %s (%s)", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    # Schema v2: artifacts list. Reject domain-sniffing v1 caches.
    if int(data.get("schema_version") or 0) < INDEX_SCHEMA:
        return None
    if not isinstance(data.get("artifacts"), list):
        return None
    return data


def save_outputs_index(run_dir: Path, index: dict[str, Any]) -> None:
    payload = {
        "schema_version": INDEX_SCHEMA,
        "artifacts": list(index.get("artifacts") or []),
    }
    with _INDEX_LOCK:
        _atomic_write(Path(run_dir) / INDEX_NAME, payload)


def _record_entry(record: Any) -> dict[str, Any] | None:
    artifact_id = str(getattr(record, "artifact_id", "") or "")
    data_path = getattr(record, "data_path", None)
    if not artifact_id or not isinstance(data_path, str) or not data_path.strip():
        return None
    meta = getattr(record, "metadata", None) or {}
    port = meta.get("port") if isinstance(meta, dict) else None
    return {
        "artifact_id": artifact_id,
        "node_id": str(getattr(record, "node_id", "") or ""),
        "node_type": str(getattr(record, "node_type", "") or ""),
        "artifact_type": str(getattr(record, "artifact_type", "") or ""),
        "data_path": data_path.replace("\\", "/"),
        "port": port,
    }


def append_artifact_source(run_dir: Path, record: Any) -> None:
    """Append (or refresh) one ArtifactStore record into the run outputs index."""
    entry = _record_entry(record)
    if entry is None:
        return
    run_dir = Path(run_dir)
    with _INDEX_LOCK:
        index = load_outputs_index(run_dir) or {
            "schema_version": INDEX_SCHEMA,
            "artifacts": [],
        }
        artifacts = [
            a
            for a in index.get("artifacts") or []
            if not (
                isinstance(a, dict) and a.get("artifact_id") == entry["artifact_id"]
            )
        ]
        artifacts.append(entry)
        index["artifacts"] = artifacts
        save_outputs_index(run_dir, index)


def build_outputs_index(run_id: str, run_dir: Path) -> dict[str, Any]:
    """Build an index solely from ArtifactStore records for this run."""
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        from app.core.artifacts.artifact_store import ArtifactStore

        for record in ArtifactStore().list(run_id=run_id):
            entry = _record_entry(record)
            if entry is None:
                continue
            aid = entry["artifact_id"]
            if aid in seen:
                continue
            seen.add(aid)
            artifacts.append(entry)
    except Exception as exc:
        logger.debug("outputs_index: ArtifactStore list failed: %s", exc)
    return {"schema_version": INDEX_SCHEMA, "artifacts": artifacts}


def ensure_outputs_index(run_id: str, run_dir: Path) -> dict[str, Any]:
    """Load index or build+persist one from ArtifactStore."""
    existing = load_outputs_index(run_dir)
    if existing is not None:
        return existing
    built = build_outputs_index(run_id, run_dir)
    try:
        save_outputs_index(run_dir, built)
    except OSError as exc:
        logger.debug("outputs_index: could not persist: %s", exc)
    return built


def artifacts_from_index(index: dict[str, Any]) -> list[dict[str, Any]]:
    """Return validated artifact entries from an index dict."""
    out: list[dict[str, Any]] = []
    for entry in index.get("artifacts") or []:
        if not isinstance(entry, dict):
            continue
        if not entry.get("artifact_id") or not entry.get("data_path"):
            continue
        out.append(entry)
    return out
