# app/core/checkpoint.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Serialize and deserialize per-node outputs to disk for
                  resumable pipeline execution.
Owns:             _write_checkpoint(), _load_checkpoint_outputs(),
                  _find_latest_checkpoint(), _update_checkpoint_index()
Public Surface:   _write_checkpoint(run_base_path, node_id, outputs, logger)
                  _load_checkpoint_outputs(checkpoint_dir) -> dict | None
                  _find_latest_checkpoint(node_id) -> dict | None
Must NOT:         Import app.models, app.domain, or any domain type at module
                  level or inline. Must not reference any artifact_type string
                  by name (e.g. "audio_samples") — all type discovery is done
                  via ArtifactSerializerRegistry.infer_type(). Must not
                  understand pipeline execution order or node logic.
Dependencies:     stdlib (json, os, logging),
                  app.core.artifact_serializer (registry — no domain knowledge),
                  app.core.config (runs_dir — lazy import only).
Reason To Change: Checkpoint storage format evolves, or new port data types
                  need serialization support.

## Manifest format (current — no legacy support)

Every checkpoint directory written by this module contains:

    manifest.json
        {
          "checkpointed_ports": ["port_a", "port_b"],
          "port_types":         {"port_a": "<type_key>", "port_b": "<type_key>"}
        }

    port_<name>/          ← one subdirectory per port
        <handler-specific files>

Both fields are required. Manifests missing either field are treated as
unreadable and the node re-executes. No legacy single-port format is supported.

All I/O is delegated to ArtifactSerializerRegistry handlers — this file
contains zero domain-model knowledge.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _write_checkpoint(
    run_base_path: str,
    node_id: str,
    outputs: dict,
    logger: Any = None,
) -> None:
    """Write a node's outputs to a checkpoint directory.

    Each serializable port is written to its own ``port_<name>/``
    subdirectory so that all ports are preserved on resume (ARCH-4 fix —
    previously only the first list port was saved).

    Supports all port types registered in ArtifactSerializerRegistry, not
    only AudioSample ports. Ports whose type has no registered handler are
    skipped with a warning (they will re-execute on resume).

    ARCH-3 fix: all I/O delegated to handlers via ArtifactSerializerRegistry.
    No domain-model imports in this function.

    Args:
        run_base_path: Base path of the current run directory.
        node_id: The node's unique ID within the pipeline.
        outputs: The node's output dict (port_name → value).
        logger: Optional PipelineLogger for structured checkpoint_failed events.
    """
    try:
        from app.core.artifact_serializer import get_serializer_registry  # noqa: PLC0415
        from pathlib import Path as _Path  # noqa: PLC0415

        # SEC: reject null bytes before any path construction — CPython raises
        # ValueError from open() but os.makedirs may succeed first on some OSes.
        if "\x00" in node_id:
            raise ValueError(
                f"node_id '{node_id!r}' contains a null byte — rejected."
            )

        checkpoint_dir = os.path.join(run_base_path, "checkpoints", f"node_{node_id}")

        # SA-C1 fix: use os.path.abspath (does NOT resolve symlinks) for the
        # prefix check. os.path.realpath resolves symlinks, allowing an attacker
        # who can create a symlink inside the run directory to escape the guard.
        checkpoint_dir_abs = os.path.abspath(checkpoint_dir)
        run_base_abs = os.path.abspath(run_base_path)
        if not checkpoint_dir_abs.startswith(run_base_abs + os.sep) and \
           checkpoint_dir_abs != run_base_abs:
            raise ValueError(
                f"node_id '{node_id}' would escape the run directory. "
                "node_id must not contain path traversal sequences."
            )
        os.makedirs(checkpoint_dir, exist_ok=True)

        # Collect ALL ports that have a registered serializer handler.
        # ARCH-3 fix: use the serializer registry's infer_type() instead of
        # duck-typing. This removes domain knowledge from platform infrastructure.
        # Unlike the previous audio-only approach, any registered type is
        # checkpointed so non-audio nodes (trainers, feature extractors, etc.)
        # are not silently skipped on resume.
        _ser_registry = get_serializer_registry()
        serializable_ports: dict[str, tuple[str, Any]] = {}  # port_name → (type_key, value)
        for port_name, value in outputs.items():
            if not isinstance(value, list) or not value:
                continue
            type_key = _ser_registry.infer_type(value)
            if type_key is None:
                continue
            handler = _ser_registry.get(type_key)
            if handler is None:
                continue
            serializable_ports[port_name] = (type_key, value)

        if not serializable_ports:
            log.warning(
                "Node '%s' has no serializable outputs — checkpoint not written; "
                "node will re-execute on resume.",
                node_id,
            )
            return

        # Write each port to its own named subdirectory.
        port_manifest: dict[str, str] = {}  # port_name → type_key
        for port_name, (type_key, value) in serializable_ports.items():
            handler = _ser_registry.get(type_key)
            port_dir = os.path.join(checkpoint_dir, f"port_{port_name}")
            os.makedirs(port_dir, exist_ok=True)
            handler.serialize(value, _Path(port_dir))
            port_manifest[port_name] = type_key

        # Write a top-level manifest atomically (tmp + os.replace) so a crash
        # between the last port write and the manifest write does not leave a
        # partial checkpoint that is silently discarded on resume — the manifest
        # is either fully written or absent, never half-written.
        top_manifest_path = os.path.join(checkpoint_dir, "manifest.json")
        tmp_manifest_path = top_manifest_path + ".tmp"
        with open(tmp_manifest_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "checkpointed_ports": sorted(port_manifest.keys()),
                    "port_types": port_manifest,
                },
                f,
                indent=2,
            )
        os.replace(tmp_manifest_path, top_manifest_path)

        # Update the per-node O(1) lookup index so _find_latest_checkpoint
        # does not need to scan all run directories.
        _update_checkpoint_index(run_base_path, node_id)

    except Exception as exc:
        log.warning("Checkpoint write failed for node '%s': %s", node_id, exc)
        if logger is not None:
            try:
                logger._emit_structured({
                    "type": "checkpoint_failed",
                    "node_id": node_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "message": (
                        f"Checkpoint write failed for node '{node_id}': {exc}. "
                        "Resume will re-execute this node."
                    ),
                })
            except Exception:
                pass


def _update_checkpoint_index(run_base_path: str, node_id: str) -> None:
    """Update the per-node checkpoint index for O(1) latest-checkpoint lookup.

    Writes ``<runs_dir>/checkpoints/node_<id>/latest_run`` containing the
    run_base_path of the most recently written checkpoint. This allows
    _find_latest_checkpoint() to skip the O(N) full-run-directory scan.

    The index file is written atomically (tmp + os.replace).
    """
    try:
        from app.core.config import runs_dir as _runs_dir  # noqa: PLC0415

        runs_dir_path = str(_runs_dir())
        index_dir = os.path.join(runs_dir_path, "checkpoints", f"node_{node_id}")
        os.makedirs(index_dir, exist_ok=True)
        index_path = os.path.join(index_dir, "latest_run")
        tmp_index_path = index_path + ".tmp"
        with open(tmp_index_path, "w", encoding="utf-8") as f:
            f.write(run_base_path)
        os.replace(tmp_index_path, index_path)
    except Exception as exc:
        # Index update failure is non-fatal — _find_latest_checkpoint falls
        # back to the full scan if the index is absent or stale.
        log.debug("Checkpoint index update failed for node '%s': %s", node_id, exc)


def _find_latest_checkpoint(node_id: str) -> dict | None:
    """Search runs/ for the most recent checkpoint for node_id.

    Uses an O(1) per-node index file written by _update_checkpoint_index()
    on every successful checkpoint write. Falls back to the O(N) full-scan
    only when the index is absent or points to a stale/missing checkpoint.

    Extracted from RunManager (SA-RJ-ARCH fix): checkpoint discovery is a
    storage query that belongs in checkpoint.py, not in the run lifecycle
    manager. RunManager.find_latest_checkpoint() now delegates here.

    Args:
        node_id: The node ID to search checkpoints for.

    Returns:
        The loaded checkpoint outputs dict, or None if not found.
    """
    from app.core.config import runs_dir as _runs_dir  # noqa: PLC0415

    runs_dir_path = str(_runs_dir())
    if not os.path.exists(runs_dir_path):
        return None

    # ── Fast path: O(1) index lookup ─────────────────────────────────────────
    index_path = os.path.join(
        runs_dir_path, "checkpoints", f"node_{node_id}", "latest_run"
    )
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                indexed_run_base = f.read().strip()
            checkpoint_dir = os.path.join(
                indexed_run_base, "checkpoints", f"node_{node_id}"
            )
            manifest_path = os.path.join(checkpoint_dir, "manifest.json")
            if os.path.exists(manifest_path):
                result = _load_checkpoint_outputs(checkpoint_dir)
                if result is not None:
                    return result
                # Index points to a corrupt/partial checkpoint — fall through
                # to full scan to find the next best candidate.
                log.debug(
                    "Checkpoint index for node '%s' pointed to an unloadable "
                    "checkpoint at '%s' — falling back to full scan.",
                    node_id, checkpoint_dir,
                )
        except Exception as exc:
            log.debug(
                "Checkpoint index read failed for node '%s': %s — falling back to full scan.",
                node_id, exc,
            )

    # ── Slow path: O(N) full scan (index absent or stale) ────────────────────
    candidates = []
    for run_dir_name in os.listdir(runs_dir_path):
        runs_dir_resolved = str(Path(runs_dir_path).resolve())
        candidate_resolved = str(Path(os.path.join(runs_dir_path, run_dir_name)).resolve())
        if not candidate_resolved.startswith(runs_dir_resolved + os.sep) and \
           candidate_resolved != runs_dir_resolved:
            log.warning(
                "Skipping suspicious run directory '%s' — resolved path escapes runs dir",
                run_dir_name,
            )
            continue
        checkpoint_dir = os.path.join(
            runs_dir_path, run_dir_name, "checkpoints", f"node_{node_id}"
        )
        manifest_path = os.path.join(checkpoint_dir, "manifest.json")
        if os.path.exists(manifest_path):
            meta_path = os.path.join(runs_dir_path, run_dir_name, "meta.json")
            created_at = ""
            if os.path.exists(meta_path):
                try:
                    with open(meta_path) as f:
                        meta = json.load(f)
                    created_at = meta.get("created_at", "")
                except Exception:
                    pass
            if not created_at:
                try:
                    mtime = os.path.getmtime(os.path.join(runs_dir_path, run_dir_name))
                    created_at = str(mtime)
                except Exception:
                    created_at = "0"
            candidates.append((created_at, checkpoint_dir))

    if not candidates:
        return None

    def _parse_ts(ts: str) -> float:
        from datetime import datetime  # noqa: PLC0415
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            try:
                return float(ts)
            except Exception:
                return 0.0

    candidates.sort(key=lambda x: _parse_ts(x[0]), reverse=True)
    return _load_checkpoint_outputs(candidates[0][1])


def _load_checkpoint_outputs(checkpoint_dir: str) -> dict | None:
    """Load checkpoint outputs from a prior run's checkpoint directory.

    Expects the current manifest format: ``manifest.json`` at the checkpoint
    root containing both ``checkpointed_ports`` (list of port names) and
    ``port_types`` (mapping of port name → artifact_type key).

    Manifests that do not contain these fields are treated as unreadable and
    the node will re-execute. No legacy format support — clean migration only.

    Returns a dict mapping port names to deserialized values on success,
    or None on failure (node will re-execute).
    """
    try:
        from app.core.artifact_serializer import get_serializer_registry  # noqa: PLC0415
        from pathlib import Path as _Path  # noqa: PLC0415

        top_manifest_path = os.path.join(checkpoint_dir, "manifest.json")
        if not os.path.exists(top_manifest_path):
            return None

        with open(top_manifest_path, "r", encoding="utf-8") as f:
            top_manifest = json.load(f)

        checkpointed_ports = top_manifest.get("checkpointed_ports")
        port_types: dict[str, str] | None = top_manifest.get("port_types")

        if checkpointed_ports is None or port_types is None:
            log.warning(
                "Checkpoint at '%s' is missing 'checkpointed_ports' or 'port_types' "
                "— unreadable format, will re-execute.",
                checkpoint_dir,
            )
            return None

        _ser_registry = get_serializer_registry()
        result: dict = {}
        for port_name in checkpointed_ports:
            port_dir = _Path(os.path.join(checkpoint_dir, f"port_{port_name}"))
            if not port_dir.exists():
                log.warning(
                    "Checkpoint port dir missing for '%s' in '%s' — will re-execute",
                    port_name, checkpoint_dir,
                )
                return None
            type_key = port_types.get(port_name)
            if type_key is None:
                log.warning(
                    "Checkpoint manifest at '%s' has no type_key for port '%s' — will re-execute",
                    checkpoint_dir, port_name,
                )
                return None
            handler = _ser_registry.get(type_key)
            if handler is None:
                log.warning(
                    "Checkpoint load: no handler for type '%s' (port '%s') — will re-execute",
                    type_key, port_name,
                )
                return None
            value = handler.deserialize(port_dir)
            if value is None:
                log.warning(
                    "Checkpoint load failed for node '%s' port '%s' — will re-execute",
                    checkpoint_dir, port_name,
                )
                return None
            result[port_name] = value
        return result

    except Exception as exc:
        log.warning(
            "Checkpoint load failed for '%s': %s — will re-execute",
            checkpoint_dir, exc,
        )
        return None
