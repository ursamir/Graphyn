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
    """Write a node's output to a checkpoint directory as WAV files + manifest.json.

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

        # Guard against path traversal via a malicious node_id.
        checkpoint_dir_resolved = os.path.realpath(checkpoint_dir)
        run_base_resolved = os.path.realpath(run_base_path)
        if not checkpoint_dir_resolved.startswith(run_base_resolved + os.sep) and \
           checkpoint_dir_resolved != run_base_resolved:
            raise ValueError(
                f"node_id '{node_id}' would escape the run directory. "
                "node_id must not contain path traversal sequences."
            )
        os.makedirs(checkpoint_dir, exist_ok=True)

        # Checkpoint the first list-of-samples output port found
        result = None
        for v in outputs.values():
            if isinstance(v, list):
                result = v
                break

        if result is None:
            return

        manifest_entries = []
        for i, sample in enumerate(result):
            filename = f"{i}.wav"
            wav_path = os.path.join(checkpoint_dir, filename)
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

        manifest_path = os.path.join(checkpoint_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"samples": manifest_entries}, f, indent=2)

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


def _load_checkpoint_outputs(checkpoint_dir: str) -> dict | None:
    """Load checkpoint outputs from a prior run's checkpoint directory.

    Reads manifest.json and reconstructs AudioSample objects from WAV files.
    Returns {"output": [AudioSample, ...]} on success, or None on failure.
    """
    try:
        import soundfile as sf
        import pydantic
        from app.models.audio_sample import AudioSample

        manifest_path = os.path.join(checkpoint_dir, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        samples = []
        for entry in manifest["samples"]:
            wav_path = os.path.join(checkpoint_dir, entry["filename"])
            data, sample_rate = sf.read(wav_path, dtype="float32", always_2d=False)
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
