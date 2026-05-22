import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional

import pydantic

from app.models.audio_sample import AudioSample

logger = logging.getLogger(__name__)

from app.core.config import cache_dir as _cache_dir

# ── Helpers to detect cacheable output types ──────────────────────────────────

def _is_audio_sample_list(value: Any) -> bool:
    """Return True if value is a non-empty list of AudioSample objects."""
    return (
        isinstance(value, list)
        and len(value) > 0
        and hasattr(value[0], "path")
        and hasattr(value[0], "sample_rate")
        and hasattr(value[0], "data")
    )


def _is_json_serializable(value: Any) -> bool:
    """Return True if value can be round-tripped through JSON."""
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


class PipelineCache:
    def __init__(self) -> None:
        self._base_override: Path | None = None

    @property
    def BASE(self) -> Path:
        if self._base_override is not None:
            return self._base_override
        return _cache_dir()

    @BASE.setter
    def BASE(self, value: Path) -> None:
        """Override the cache base directory.

        This setter exists for test isolation only — use ``monkeypatch`` on
        ``app.core.config.cache_dir`` in production test suites instead.
        It is not part of the public API and may be removed in a future version.
        """
        self._base_override = value

    def key(self, node_type: str, config: dict, input_hash: str) -> str:
        """SHA-256 of node_type + sorted_json(config) + input_hash."""
        sorted_config = json.dumps(config, sort_keys=True)
        raw = node_type + sorted_config + input_hash
        return hashlib.sha256(raw.encode()).hexdigest()

    def input_hash(self, inputs: Any) -> str:
        """Compute a stable hash for any node input value.

        Supports:
        - list[AudioSample] — hashed by path + sample_rate + data shape
        - list of Pydantic models — hashed via model_dump JSON
        - numpy ndarray — hashed via raw bytes (stable across runs)
        - JSON-serializable dicts/lists — hashed via sorted JSON
        - Fallback — hashed via repr() (stable within a process only)
        """
        if isinstance(inputs, list) and len(inputs) > 0:
            first = inputs[0]
            if hasattr(first, "path") and hasattr(first, "sample_rate") and hasattr(first, "data"):
                # AudioSample list (original behaviour)
                parts = []
                for sample in inputs:
                    shape = sample.data.shape if sample.data is not None else ()
                    path = getattr(sample, "path", None) or getattr(sample, "source_path", str(id(sample)))
                    sr = getattr(sample, "sample_rate", 0)
                    parts.append(f"{path}:{sr}:{shape}")
                raw = "".join(parts)
                return hashlib.sha256(raw.encode()).hexdigest()
            if hasattr(first, "model_dump"):
                # List of Pydantic models — may contain non-serializable types (e.g. numpy arrays)
                try:
                    raw = json.dumps([item.model_dump(mode="json") for item in inputs], sort_keys=True)
                    return hashlib.sha256(raw.encode()).hexdigest()
                except Exception:
                    pass  # Fall through to numpy / repr() fallback

        # Single Pydantic model (e.g. DatasetArtifact passed to trainer.dataset port)
        if hasattr(inputs, "model_dump"):
            try:
                raw = json.dumps(inputs.model_dump(mode="json"), sort_keys=True)
                return hashlib.sha256(raw.encode()).hexdigest()
            except Exception:
                pass  # Fall through to numpy / repr() fallback

        # numpy ndarray — hash raw bytes for cross-run stability
        try:
            import numpy as np  # noqa: PLC0415
            if isinstance(inputs, np.ndarray):
                return hashlib.sha256(inputs.tobytes()).hexdigest()
            # List of numpy arrays
            if isinstance(inputs, list) and inputs and isinstance(inputs[0], np.ndarray):
                h = hashlib.sha256()
                for arr in inputs:
                    h.update(arr.tobytes())
                return h.hexdigest()
        except ImportError:
            pass

        if _is_json_serializable(inputs):
            raw = json.dumps(inputs, sort_keys=True, default=str)
            return hashlib.sha256(raw.encode()).hexdigest()

        # Last-resort fallback: repr() is stable within a process but NOT across
        # restarts. Nodes that reach this path should be marked cacheable=False.
        logger.warning(
            "PipelineCache.input_hash: falling back to repr() for type %s — "
            "cache keys will not be stable across process restarts. "
            "Mark this node cacheable=False to suppress this warning.",
            type(inputs).__name__,
        )
        return hashlib.sha256(repr(inputs).encode()).hexdigest()

    def _cache_dir(self, cache_key: str) -> Path:
        return self.BASE / cache_key

    def has(self, cache_key: str) -> bool:
        """Return True if a cache entry exists for key.

        .. warning::
            TOCTOU: the entry may be deleted between has() and load().
            Always treat load() returning None as a cache miss, regardless
            of what has() returned. Prefer calling load() directly.
        """
        return self._cache_dir(cache_key).is_dir()

    def load(self, cache_key: str) -> Optional[Any]:
        """Load cached node outputs.

        Supports two storage formats:
        - ``outputs.json`` — generic JSON-serializable outputs dict (new)
        - ``manifest.json`` — legacy AudioSample WAV cache (original)

        Returns the outputs dict on success, or None on failure.
        """
        cache_dir = self._cache_dir(cache_key)

        # ── New generic format ─────────────────────────────────────────────────
        outputs_path = cache_dir / "outputs.json"
        if outputs_path.exists():
            try:
                with open(outputs_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning(
                    "Cache read (outputs.json) failed for key %s (%s) — will re-execute",
                    cache_key, exc,
                )
                return None

        # ── Multi-port AudioSample format (port_<name>/ subdirectories) ─────────
        # Introduced by G2-17: each AudioSample port is stored in its own
        # subdirectory named port_<port_name>/ containing manifest.json + wavs.
        port_dirs = [
            d for d in cache_dir.iterdir()
            if d.is_dir() and d.name.startswith("port_")
        ] if cache_dir.is_dir() else []

        if port_dirs:
            try:
                import soundfile as sf
                result: dict = {}
                for port_dir in port_dirs:
                    port_name = port_dir.name[len("port_"):]
                    port_manifest_path = port_dir / "manifest.json"
                    if not port_manifest_path.exists():
                        continue
                    with open(port_manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    samples = []
                    for entry in manifest["samples"]:
                        wav_path = port_dir / entry["filename"]
                        data, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=False)
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
                                "Cache entry validation failed for key %s port %s (%s) — skipping",
                                cache_key, port_name, exc,
                            )
                            return None
                        samples.append(sample)
                    result[port_name] = samples
                if result:
                    return result
            except Exception as exc:
                logger.warning(
                    "Cache read (port subdirs) failed for key %s (%s) — will re-execute",
                    cache_key, exc,
                )
                return None

        # ── Legacy AudioSample format (flat manifest.json at cache root) ────────
        # Written by versions prior to G2-17. Only a single "output" port was
        # stored. Kept for backward compatibility with existing cache entries.
        manifest_path = cache_dir / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            import soundfile as sf
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            samples = []
            for entry in manifest["samples"]:
                wav_path = cache_dir / entry["filename"]
                data, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=False)
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
                        "Cache entry validation failed for key %s (%s) — skipping",
                        cache_key, exc,
                    )
                    return None
                samples.append(sample)

            # Return in the standard outputs-dict shape
            return {"output": samples}

        except Exception as exc:
            logger.warning(
                "Cache read (manifest.json) failed for key %s (%s) — will re-execute",
                cache_key, exc,
            )
            return None

    def save(self, cache_key: str, outputs: Any) -> None:
        """Save node outputs to cache.

        ``outputs`` may be:
        - A dict mapping port names to values (standard node output shape)
        - A list[AudioSample] (legacy call-site compatibility)

        Storage strategy:
        - If the outputs dict contains an AudioSample list on any port → WAV + manifest.json
        - Otherwise → outputs.json (JSON-serializable values only; skips non-serializable)
        """
        cache_dir = self._cache_dir(cache_key)
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Normalise legacy list input to dict
        if isinstance(outputs, list):
            outputs = {"output": outputs}

        if not isinstance(outputs, dict):
            logger.debug("Cache.save: outputs is not a dict — skipping cache write")
            return

        # ── Check for AudioSample list on any port ─────────────────────────────
        # Collect ALL ports that carry AudioSample data so none are dropped.
        audio_ports: dict[str, list] = {
            port_name: value
            for port_name, value in outputs.items()
            if _is_audio_sample_list(value)
        }

        if audio_ports:
            import numpy as np
            import soundfile as sf
            # Write each AudioSample port to its own named subdirectory so that
            # all ports are preserved (previously only the first port was saved).
            for port_name, audio_samples in audio_ports.items():
                port_dir = cache_dir / f"port_{port_name}"
                port_dir.mkdir(parents=True, exist_ok=True)
                manifest_entries = []
                for i, sample in enumerate(audio_samples):
                    filename = f"{i}.wav"
                    wav_path = port_dir / filename
                    if sample.data is not None and len(sample.data) > 0:
                        sf.write(str(wav_path), sample.data, sample.sample_rate)
                    else:
                        sf.write(str(wav_path), np.array([], dtype=np.float32), sample.sample_rate)
                    manifest_entries.append({
                        "filename": filename,
                        "label": sample.label,
                        "path": sample.path,
                        "sample_rate": sample.sample_rate,
                        "metadata": sample.metadata,
                    })
                manifest = {"samples": manifest_entries}
                manifest_path = port_dir / "manifest.json"
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)
            return

        # ── Generic JSON format for all other output types ─────────────────────
        serializable: dict = {}
        skipped_ports: list[str] = []
        for port_name, value in outputs.items():
            if _is_json_serializable(value):
                serializable[port_name] = value
            elif hasattr(value, "model_dump"):
                # Pydantic model
                try:
                    serializable[port_name] = value.model_dump(mode="json")
                except Exception:
                    skipped_ports.append(port_name)
            else:
                skipped_ports.append(port_name)

        if skipped_ports:
            logger.warning(
                "Cache.save: skipping non-serializable port(s) %s — "
                "these outputs will not be cached and the node will re-execute on the next run. "
                "Mark the node cacheable=False to suppress this warning.",
                skipped_ports,
            )

        if not serializable:
            logger.warning(
                "Cache.save: no serializable ports in outputs — skipping cache write entirely."
            )
            return

        outputs_path = cache_dir / "outputs.json"
        with open(outputs_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)

    def clear(self) -> dict:
        """Delete all cache entries. Returns {entries_deleted, bytes_freed}."""
        if not self.BASE.is_dir():
            return {"entries_deleted": 0, "bytes_freed": 0}

        entries_deleted = 0
        bytes_freed = 0

        for entry in self.BASE.iterdir():
            if entry.is_dir():
                for file in entry.rglob("*"):
                    if file.is_file():
                        bytes_freed += file.stat().st_size
                shutil.rmtree(entry)
                entries_deleted += 1

        return {"entries_deleted": entries_deleted, "bytes_freed": bytes_freed}
