# app/core/checkpoint.py
"""Checkpoint read/write for resumable pipeline execution.

Extracted from pipeline.py. Responsible for:
  - _write_checkpoint  — serialize node outputs to disk for resume
  - _load_checkpoint_outputs — reconstruct node outputs from a checkpoint dir
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

    Args:
        run_base_path: Base path of the current run directory.
        node_id: The node's unique ID within the pipeline.
        outputs: The node's output dict (port_name → value).
        logger: Optional PipelineLogger for structured checkpoint_failed events.
    """
    try:
        import soundfile as sf
        import numpy as np

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

        # Write each port to its own named subdirectory (matches pipeline_cache.py format).
        for port_name, samples in audio_ports.items():
            port_dir = os.path.join(checkpoint_dir, f"port_{port_name}")
            os.makedirs(port_dir, exist_ok=True)

            manifest_entries = []
            for i, sample in enumerate(samples):
                filename = f"{i}.wav"
                wav_path = os.path.join(port_dir, filename)
                if sample.data is not None and len(sample.data) > 0:
                    sf.write(wav_path, sample.data, sample.sample_rate)
                else:
                    sf.write(wav_path, np.array([], dtype=np.float32), sample.sample_rate)
                manifest_entries.append({
                    "filename": filename,
                    "label": sample.label,
                    "path": sample.path,
                    "sample_rate": sample.sample_rate,
                    "metadata": sample.metadata,
                })

            manifest_path = os.path.join(port_dir, "manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump({"samples": manifest_entries}, f, indent=2)

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

    Returns a dict mapping port names to lists of AudioSample objects on
    success, or None on failure.
    """
    try:
        import soundfile as sf
        import pydantic
        from app.models.audio_sample import AudioSample

        top_manifest_path = os.path.join(checkpoint_dir, "manifest.json")
        if not os.path.exists(top_manifest_path):
            return None

        with open(top_manifest_path, "r", encoding="utf-8") as f:
            top_manifest = json.load(f)

        # ── New multi-port format ──────────────────────────────────────────────
        checkpointed_ports = top_manifest.get("checkpointed_ports")
        if checkpointed_ports is not None:
            result: dict = {}
            for port_name in checkpointed_ports:
                port_dir = os.path.join(checkpoint_dir, f"port_{port_name}")
                port_manifest_path = os.path.join(port_dir, "manifest.json")
                if not os.path.exists(port_manifest_path):
                    log.warning(
                        "Checkpoint port dir missing for '%s' in '%s' — will re-execute",
                        port_name, checkpoint_dir,
                    )
                    return None
                with open(port_manifest_path, "r", encoding="utf-8") as f:
                    port_manifest = json.load(f)
                samples = []
                for entry in port_manifest["samples"]:
                    wav_path = os.path.join(port_dir, entry["filename"])
                    try:
                        data, sample_rate = sf.read(wav_path, dtype="float32", always_2d=False)
                    except Exception as exc:
                        # SA-C3 fix: include wav_path in the error message so
                        # operators can identify which file is missing/corrupt.
                        log.warning(
                            "Checkpoint load failed for node '%s' port '%s' "
                            "(file: %s): %s — will re-execute",
                            checkpoint_dir, port_name, wav_path, exc,
                        )
                        return None
                    try:
                        sample = AudioSample.model_validate({
                            "path": entry["path"],
                            "sample_rate": entry["sample_rate"],
                            "data": data,
                            "label": entry["label"],
                            "metadata": entry.get("metadata", {}),
                        })
                    except pydantic.ValidationError as exc:
                        log.warning(
                            "Checkpoint entry validation failed for '%s' port '%s': %s — will re-execute",
                            checkpoint_dir, port_name, exc,
                        )
                        return None
                    samples.append(sample)
                result[port_name] = samples
            return result

        # ── Legacy single-port format (flat manifest.json) ────────────────────
        samples = []
        for entry in top_manifest.get("samples", []):
            wav_path = os.path.join(checkpoint_dir, entry["filename"])
            try:
                data, sample_rate = sf.read(wav_path, dtype="float32", always_2d=False)
            except Exception as exc:
                # SA-C3 fix: include wav_path in the error message.
                log.warning(
                    "Checkpoint load failed for '%s' (file: %s): %s — will re-execute",
                    checkpoint_dir, wav_path, exc,
                )
                return None
            try:
                sample = AudioSample.model_validate({
                    "path": entry["path"],
                    "sample_rate": entry["sample_rate"],
                    "data": data,
                    "label": entry["label"],
                    "metadata": entry.get("metadata", {}),
                })
            except pydantic.ValidationError as exc:
                log.warning(
                    "Checkpoint entry validation failed for '%s': %s — will re-execute",
                    checkpoint_dir, exc,
                )
                return None
            samples.append(sample)

        return {"output": samples}

    except Exception as exc:
        log.warning(
            "Checkpoint load failed for '%s': %s — will re-execute",
            checkpoint_dir, exc,
        )
        return None
