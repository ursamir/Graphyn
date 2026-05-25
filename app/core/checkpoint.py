# app/core/checkpoint.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Serialize and deserialize per-node outputs to disk for
                  resumable pipeline execution.
Owns:             _write_checkpoint(), _load_checkpoint_outputs()
Public Surface:   _write_checkpoint(run_base_path, node_id, outputs, logger)
                  _load_checkpoint_outputs(checkpoint_dir) -> dict | None
Must NOT:         Import app.models at module level (RULE 1 — platform must
                  not depend on domain models at import time). AudioSample is
                  never imported here — WAV I/O is delegated to
                  AudioSampleHandler via ArtifactSerializerRegistry.
                  Must not understand pipeline execution order or node logic.
Dependencies:     stdlib (json, os, logging),
                  app.core.artifact_serializer (registry — no domain knowledge).
Reason To Change: Checkpoint storage format evolves, or new port data types
                  need serialization support.

## ARCH-3 fix

All WAV I/O and AudioSample construction previously inline in
_write_checkpoint() and _load_checkpoint_outputs() has been removed.
Both functions now delegate to ArtifactSerializerRegistry:

    registry = get_serializer_registry()
    handler  = registry.get("audio_samples")   # None if not registered
    if handler:
        handler.serialize(samples, port_dir)
        samples = handler.deserialize(port_dir)

This means checkpoint.py contains zero domain-model imports.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)


def _write_checkpoint(
    run_base_path: str,
    node_id: str,
    outputs: dict,
    logger: Any = None,
) -> None:
    """Write a node's outputs to a checkpoint directory as WAV files + manifest.json.

    Each list-of-AudioSample port is written to its own ``port_<name>/``
    subdirectory so that all ports are preserved on resume (ARCH-4 fix —
    previously only the first list port was saved).

    ARCH-3 fix: WAV I/O delegated to AudioSampleHandler via
    ArtifactSerializerRegistry. No domain-model imports in this function.

    Args:
        run_base_path: Base path of the current run directory.
        node_id: The node's unique ID within the pipeline.
        outputs: The node's output dict (port_name → value).
        logger: Optional PipelineLogger for structured checkpoint_failed events.
    """
    try:
        from app.core.artifact_serializer import get_serializer_registry  # noqa: PLC0415

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

        # Collect ALL ports that carry AudioSample-like lists so none are dropped.
        audio_ports: dict[str, list] = {
            port_name: value
            for port_name, value in outputs.items()
            if isinstance(value, list) and value and _is_audio_sample_list(value)
        }

        if not audio_ports:
            # SA-C2 fix: warn when a node has no audio outputs so users know
            # it will re-execute on resume rather than being silently skipped.
            log.warning(
                "Node '%s' has no AudioSample outputs — checkpoint not written; "
                "node will re-execute on resume.",
                node_id,
            )
            return

        handler = get_serializer_registry().get("audio_samples")
        if handler is None:
            log.warning(
                "Node '%s': no handler registered for 'audio_samples' — checkpoint not written; "
                "node will re-execute on resume. Call register_audio_serializer() at startup.",
                node_id,
            )
            return

        # Write each port to its own named subdirectory (matches pipeline_cache.py format).
        for port_name, samples in audio_ports.items():
            port_dir = os.path.join(checkpoint_dir, f"port_{port_name}")
            os.makedirs(port_dir, exist_ok=True)
            from pathlib import Path as _Path  # noqa: PLC0415
            handler.serialize(samples, _Path(port_dir))

        # Write a top-level manifest listing which ports were checkpointed.
        top_manifest_path = os.path.join(checkpoint_dir, "manifest.json")
        with open(top_manifest_path, "w", encoding="utf-8") as f:
            json.dump({"checkpointed_ports": sorted(audio_ports.keys())}, f, indent=2)

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


def _is_audio_sample_list(value: list) -> bool:
    """Return True if value looks like a list of AudioSample objects."""
    first = value[0]
    return (
        hasattr(first, "data")
        and hasattr(first, "sample_rate")
        and hasattr(first, "label")
    )


def _load_checkpoint_outputs(checkpoint_dir: str) -> dict | None:
    """Load checkpoint outputs from a prior run's checkpoint directory.

    Supports two formats:
    - New multi-port format: ``port_<name>/manifest.json`` per port
    - Legacy single-port format: flat ``manifest.json`` at checkpoint root

    ARCH-3 fix: AudioSample construction delegated to AudioSampleHandler via
    ArtifactSerializerRegistry. No domain-model imports in this function.

    Returns a dict mapping port names to lists of AudioSample objects on
    success, or None on failure.
    """
    try:
        from app.core.artifact_serializer import get_serializer_registry  # noqa: PLC0415
        from pathlib import Path as _Path  # noqa: PLC0415

        top_manifest_path = os.path.join(checkpoint_dir, "manifest.json")
        if not os.path.exists(top_manifest_path):
            return None

        with open(top_manifest_path, "r", encoding="utf-8") as f:
            top_manifest = json.load(f)

        handler = get_serializer_registry().get("audio_samples")
        if handler is None:
            log.warning(
                "Checkpoint load: no handler registered for 'audio_samples' — will re-execute. "
                "Call register_audio_serializer() at startup.",
            )
            return None

        # ── New multi-port format ──────────────────────────────────────────────
        checkpointed_ports = top_manifest.get("checkpointed_ports")
        if checkpointed_ports is not None:
            result: dict = {}
            for port_name in checkpointed_ports:
                port_dir = _Path(os.path.join(checkpoint_dir, f"port_{port_name}"))
                if not port_dir.exists():
                    log.warning(
                        "Checkpoint port dir missing for '%s' in '%s' — will re-execute",
                        port_name, checkpoint_dir,
                    )
                    return None
                samples = handler.deserialize(port_dir)
                if samples is None:
                    log.warning(
                        "Checkpoint load failed for node '%s' port '%s' — will re-execute",
                        checkpoint_dir, port_name,
                    )
                    return None
                result[port_name] = samples
            return result

        # ── Legacy single-port format (flat manifest.json) ────────────────────
        # The top-level manifest.json IS the samples manifest in this format.
        # Pass the checkpoint_dir itself as the src_dir so the handler can
        # find the WAV files alongside the manifest.
        samples = handler.deserialize(_Path(checkpoint_dir))
        if samples is None:
            return None
        return {"output": samples}

    except Exception as exc:
        log.warning(
            "Checkpoint load failed for '%s': %s — will re-execute",
            checkpoint_dir, exc,
        )
        return None
