# app/models/audio_artifact_serializer.py
"""
Bounded Context:  Domain — Audio Data Models
Responsibility:   Domain-side implementation of ArtifactTypeHandler for the
                  ``audio_samples`` artifact type. Owns all WAV I/O, manifest
                  format, and AudioSample duck-typing logic that previously
                  lived inside platform infrastructure.
Owns:             AudioSampleHandler (ArtifactTypeHandler impl),
                  register_audio_serializer().
Public Surface:   register_audio_serializer() — called once at startup from
                  each entry point (API, CLI, MCP).
Must NOT:         Import from app.core.orchestrator, app.core.executor,
                  app.core.planner, or any other execution-layer module.
                  Must not register itself at import time — only when
                  register_audio_serializer() is explicitly called.
Dependencies:     app.core.artifact_serializer (interface only — no domain
                  knowledge flows back), app.models.audio_sample, soundfile,
                  numpy, json, hashlib, pathlib.
Reason To Change: AudioSample schema changes, WAV manifest format evolves,
                  or a new audio serialization format (e.g. FLAC) is adopted.

## Manifest format (artifacts/{id}/data/ and cache/port_<name>/)

    manifest.json
    {
        "samples": [
            {
                "filename": "0.wav",
                "label": "speech",
                "path": "/original/source/path.wav",
                "sample_rate": 16000,
                "metadata": {}
            },
            ...
        ]
    }

WAV files are written alongside manifest.json in the same directory.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AudioSampleHandler:
    """ArtifactTypeHandler implementation for ``audio_samples``.

    Handles serialize/deserialize of ``list[AudioSample]`` to/from a
    directory containing WAV files and a ``manifest.json``.
    """

    # ------------------------------------------------------------------
    # ArtifactTypeHandler interface
    # ------------------------------------------------------------------

    def serialize(self, data: Any, dest_dir: Path) -> None:
        """Write a list[AudioSample] to ``dest_dir`` as WAV + manifest.json.

        Writes to a temporary sibling directory first, then atomically renames
        to ``dest_dir`` on success.  On failure the temp directory is cleaned
        up so no orphaned partial WAV files are left on disk.
        """
        import shutil
        import tempfile

        import numpy as np
        import soundfile as sf

        if not isinstance(data, list):
            raise TypeError(f"Expected list[AudioSample], got {type(data).__name__}")

        # Write to a temp dir so a mid-write failure leaves dest_dir untouched.
        tmp_dir = Path(tempfile.mkdtemp(dir=dest_dir.parent, prefix=".tmp_audio_"))
        try:
            manifest_entries = []
            for i, sample in enumerate(data):
                filename = f"{i}.wav"
                wav_path = tmp_dir / filename
                sample_data = getattr(sample, "data", None)
                sample_rate = getattr(sample, "sample_rate", 22050)
                if sample_data is not None and len(sample_data) > 0:
                    sf.write(str(wav_path), sample_data, sample_rate)
                else:
                    sf.write(str(wav_path), np.array([], dtype=np.float32), sample_rate)
                manifest_entries.append({
                    "filename": filename,
                    "label": getattr(sample, "label", None),
                    "path": getattr(sample, "path", None) or getattr(sample, "source_path", ""),
                    "sample_rate": sample_rate,
                    "metadata": getattr(sample, "metadata", {}),
                })
            (tmp_dir / "manifest.json").write_text(
                json.dumps({"samples": manifest_entries}, indent=2), encoding="utf-8"
            )
            # Atomic promotion: remove dest_dir if it already exists, then rename.
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            tmp_dir.rename(dest_dir)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def deserialize(self, src_dir: Path) -> Any | None:
        """Read WAV + manifest.json from ``src_dir`` → list[AudioSample].

        Returns ``None`` if the manifest is missing (cache/checkpoint miss).
        """
        import pydantic
        import soundfile as sf
        from app.models.audio_sample import AudioSample

        manifest_path = src_dir / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("AudioSampleHandler.deserialize: corrupt manifest at %s (%s)", src_dir, exc)
            return None

        samples = []
        for entry in manifest.get("samples", []):
            wav_path = src_dir / entry["filename"]
            try:
                data, _sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
            except Exception as exc:
                logger.warning(
                    "AudioSampleHandler.deserialize: skipping corrupt WAV %s (%s)",
                    wav_path, exc,
                )
                continue  # skip this sample; return the rest of the valid samples
            try:
                sample = AudioSample.model_validate({
                    "path": entry["path"],
                    "sample_rate": entry["sample_rate"],
                    "data": data,
                    "label": entry["label"],
                    "metadata": entry.get("metadata", {}),
                })
            except pydantic.ValidationError as exc:
                logger.warning(
                    "AudioSampleHandler.deserialize: skipping invalid entry %s (%s)",
                    wav_path, exc,
                )
                continue  # skip this sample; return the rest of the valid samples
            samples.append(sample)
        return samples

    def compute_content_hash_input(self, data: Any) -> str:
        """Return a stable JSON string for SHA-256 hashing of a list[AudioSample]."""
        manifest_entries = []
        for sample in data:
            path = getattr(sample, "path", None) or getattr(sample, "source_path", str(id(sample)))
            sr = getattr(sample, "sample_rate", 0)
            raw_data = getattr(sample, "data", None)
            shape = tuple(raw_data.shape) if raw_data is not None else ()
            label = getattr(sample, "label", None)
            # Include a short PCM hash to distinguish files with identical
            # metadata but different audio content (prevents false deduplication).
            if raw_data is not None and hasattr(raw_data, "tobytes"):
                try:
                    # Hash only the first 1024 float32 values (4 KB) combined
                    # with shape+dtype for a fast, stable fingerprint.  Hashing
                    # the full array for large files (e.g. 10-min @ 44100 Hz =
                    # ~106 MB) would materialise hundreds of MB per cache check.
                    prefix = raw_data.flat[:1024].tobytes()
                    pcm_hash = hashlib.sha256(prefix).hexdigest()[:16]
                except Exception:
                    pcm_hash = ""
            else:
                pcm_hash = ""
            manifest_entries.append({
                "path": path,
                "sample_rate": sr,
                "shape": list(shape),
                "label": label,
                "pcm_hash": pcm_hash,
            })
        return json.dumps(manifest_entries, sort_keys=True)

    def infer_type(self, value: Any) -> str | None:
        """Return ``"audio_samples"`` if ``value`` is a non-empty list of AudioSample-like objects."""
        # First try exact type check (fast path, avoids duck-typing overhead)
        try:
            from app.models.audio_sample import AudioSample
            if isinstance(value, list) and value and isinstance(value[0], AudioSample):
                return "audio_samples"
        except ImportError:
            pass

        # Duck-type fallback: any list whose first element has .data + .sample_rate
        if (
            isinstance(value, list)
            and value
            and hasattr(value[0], "data")
            and hasattr(value[0], "sample_rate")
        ):
            return "audio_samples"

        return None


# ---------------------------------------------------------------------------
# Registration entry point
# ---------------------------------------------------------------------------


def register_audio_serializer() -> None:
    """Register the AudioSampleHandler with the platform serializer registry.

    Call this once at application startup from each entry point:
        from app.models.audio_artifact_serializer import register_audio_serializer
        register_audio_serializer()

    Idempotent — safe to call multiple times (re-registers the same handler).
    """
    from app.core.artifact_serializer import get_serializer_registry
    registry = get_serializer_registry()
    handler = AudioSampleHandler()
    registry.register("audio_samples", handler)
    logger.debug("AudioSampleHandler registered for artifact_type='audio_samples'")
