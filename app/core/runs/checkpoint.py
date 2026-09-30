# app/core/runs/checkpoint.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Serialize and deserialize per-node outputs to disk for
                  resumable pipeline execution.
Owns:             _write_checkpoint(), _load_checkpoint_outputs(),
                  _find_latest_checkpoint(), _update_checkpoint_index()
Public Surface:   _write_checkpoint(run_base_path, node_id, outputs, logger)
                  _load_checkpoint_outputs(checkpoint_dir) -> dict | None
                  _find_latest_checkpoint(node_id, graph_hash, *,
                      source_run_id=None) -> dict | None  (graph-hash filtered)
Must NOT:         Import app.models, app.domain, or any domain type at module
                  level or inline. Must not reference any artifact_type string
                  by name (e.g. "audio_samples") — all type discovery is done
                  via ArtifactSerializerRegistry.infer_type(). Must not
                  understand pipeline execution order or node logic.
Dependencies:     stdlib (json, os, logging),
                  app.core.artifacts.artifact_serializer (registry — no domain knowledge),
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
    graph_hash: str | None = None,
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
        from app.core.artifacts.artifact_serializer import get_serializer_registry  # noqa: PLC0415
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
        all_ports = sorted(outputs.keys())
        with open(tmp_manifest_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "checkpointed_ports": sorted(port_manifest.keys()),
                    "port_types": port_manifest,
                    "all_ports": all_ports,
                    "graph_hash": graph_hash or "",
                },
                f,
                indent=2,
            )
        os.replace(tmp_manifest_path, top_manifest_path)

        # Update the per-node O(1) lookup index so _find_latest_checkpoint
        # does not need to scan all run directories.
        _update_checkpoint_index(run_base_path, node_id, graph_hash=graph_hash or "")

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


def _update_checkpoint_index(
    run_base_path: str,
    node_id: str,
    *,
    graph_hash: str,
) -> None:
    """Update the per-node checkpoint index for O(1) latest-checkpoint lookup.

    Writes ``<runs_dir>/checkpoints/<graph_hash>/node_<id>/latest_run`` containing
    the run_base_path of the most recently written checkpoint. This allows
    _find_latest_checkpoint() to skip the O(N) full-run-directory scan.

    The index file is written atomically (tmp + os.replace).
    """
    try:
        from app.core.config import runs_dir as _runs_dir  # noqa: PLC0415

        runs_dir_path = str(_runs_dir())
        gh = graph_hash or "_unknown"
        index_dir = os.path.join(
            runs_dir_path, "checkpoints", gh, f"node_{node_id}"
        )
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


def _checkpoint_graph_hash(checkpoint_dir: str, run_dir: str) -> str:
    """Logical graph hash a checkpoint was written for ('' when unknown).

    Prefers the hash stamped in the checkpoint manifest; falls back to the
    owning run's meta.json / resume_state.json.
    """
    try:
        with open(os.path.join(checkpoint_dir, "manifest.json"), encoding="utf-8") as f:
            gh = json.load(f).get("graph_hash")
        if isinstance(gh, str) and gh:
            return gh
    except Exception:
        pass
    for name in ("meta.json", "resume_state.json"):
        try:
            with open(os.path.join(run_dir, name), encoding="utf-8") as f:
                gh = json.load(f).get("graph_hash")
            if isinstance(gh, str) and gh:
                return gh
        except Exception:
            continue
    return ""


def _find_latest_checkpoint(
    node_id: str,
    graph_hash: str | None = None,
    *,
    source_run_id: str | None = None,
) -> dict | None:
    """Return outputs of the most recent checkpoint of ``node_id`` for ``graph_hash``.

    Only checkpoints written for the same *logical* graph hash are eligible —
    a node id like ``clean`` is shared by many unrelated projects, and
    returning another graph's outputs would silently feed wrong data into a
    partial run. Without a graph hash nothing can be verified → None.

    Uses the O(1) per-graph-hash index written by _update_checkpoint_index();
    falls back to an O(N) scan of run dirs filtered by graph hash. With
    ``source_run_id`` only that run's checkpoint is considered.
    """
    from app.core.config import runs_dir as _runs_dir  # noqa: PLC0415

    gh = graph_hash or ""
    if not gh:
        return None
    runs_dir_path = str(_runs_dir())
    if not os.path.exists(runs_dir_path):
        return None
    runs_dir_resolved = str(Path(runs_dir_path).resolve())

    def _safe_run_dir(name: str) -> str | None:
        candidate = os.path.join(runs_dir_path, name)
        resolved = str(Path(candidate).resolve())
        if not resolved.startswith(runs_dir_resolved + os.sep):
            log.warning(
                "Skipping suspicious run directory '%s' — resolved path escapes runs dir",
                name,
            )
            return None
        return candidate

    if source_run_id:
        run_dir = _safe_run_dir(source_run_id)
        if run_dir is None:
            return None
        checkpoint_dir = os.path.join(run_dir, "checkpoints", f"node_{node_id}")
        if not os.path.exists(os.path.join(checkpoint_dir, "manifest.json")):
            return None
        if _checkpoint_graph_hash(checkpoint_dir, run_dir) != gh:
            return None
        return _load_checkpoint_outputs(checkpoint_dir)

    # ── Fast path: O(1) index lookup ─────────────────────────────────────────
    index_path = os.path.join(
        runs_dir_path, "checkpoints", gh, f"node_{node_id}", "latest_run"
    )
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                indexed_run_base = f.read().strip()
            checkpoint_dir = os.path.join(
                indexed_run_base, "checkpoints", f"node_{node_id}"
            )
            if (
                os.path.exists(os.path.join(checkpoint_dir, "manifest.json"))
                and _checkpoint_graph_hash(checkpoint_dir, indexed_run_base) == gh
            ):
                result = _load_checkpoint_outputs(checkpoint_dir)
                if result is not None:
                    return result
            log.debug(
                "Checkpoint index for node '%s' is stale/unloadable at '%s' — full scan.",
                node_id, checkpoint_dir,
            )
        except Exception as exc:
            log.debug(
                "Checkpoint index read failed for node '%s': %s — falling back to full scan.",
                node_id, exc,
            )

    # ── Slow path: O(N) scan, filtered by graph hash ─────────────────────────
    candidates = []
    for run_dir_name in os.listdir(runs_dir_path):
        if run_dir_name == "checkpoints":
            continue
        run_dir = _safe_run_dir(run_dir_name)
        if run_dir is None:
            continue
        checkpoint_dir = os.path.join(run_dir, "checkpoints", f"node_{node_id}")
        if not os.path.exists(os.path.join(checkpoint_dir, "manifest.json")):
            continue
        if _checkpoint_graph_hash(checkpoint_dir, run_dir) != gh:
            continue
        created_at = ""
        meta_path = os.path.join(run_dir, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    created_at = json.load(f).get("created_at", "")
            except Exception:
                pass
        if not created_at:
            try:
                created_at = str(os.path.getmtime(run_dir))
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
    for _ts, checkpoint_dir in candidates:
        result = _load_checkpoint_outputs(checkpoint_dir)
        if result is not None:
            return result
    return None


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
        from app.core.artifacts.artifact_serializer import get_serializer_registry  # noqa: PLC0415
        from pathlib import Path as _Path  # noqa: PLC0415

        top_manifest_path = os.path.join(checkpoint_dir, "manifest.json")
        if not os.path.exists(top_manifest_path):
            return None

        with open(top_manifest_path, "r", encoding="utf-8") as f:
            top_manifest = json.load(f)

        checkpointed_ports = top_manifest.get("checkpointed_ports")
        port_types: dict[str, str] | None = top_manifest.get("port_types")
        all_ports = top_manifest.get("all_ports")

        if checkpointed_ports is None or port_types is None:
            log.warning(
                "Checkpoint at '%s' is missing 'checkpointed_ports' or 'port_types' "
                "— unreadable format, will re-execute.",
                checkpoint_dir,
            )
            return None

        if all_ports is not None:
            if sorted(checkpointed_ports) != sorted(all_ports):
                log.warning(
                    "Checkpoint at '%s' is partial (checkpointed %s vs all_ports %s) "
                    "— will re-execute.",
                    checkpoint_dir,
                    checkpointed_ports,
                    all_ports,
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

# Public names. A leading underscore stays private to this module.
find_latest_checkpoint = _find_latest_checkpoint
write_checkpoint = _write_checkpoint
load_checkpoint_outputs = _load_checkpoint_outputs
