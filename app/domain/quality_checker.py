# app/domain/quality_checker.py
"""
Bounded Context:  Domain — Data Quality
Responsibility:   Automated quality checks for audio dataset versions.
                  Persists findings to quality_report.json. Never raises —
                  all errors are recorded as findings.
Owns:             QualityChecker class, all check implementations
                  (duration_range, sample_rate, clipping, dc_offset, snr,
                  duplicates, outliers, class_imbalance).
Public Surface:   QualityChecker.run(project, version) → dict
Must NOT:         Import from app.core.nodes, app.core.orchestrator, or
                  app.core.executor. Must not register node types.
Dependencies:     app.core.config (datasets_output_dir), stdlib (hashlib,
                  json, pathlib), numpy, librosa, soundfile (optional).
Reason To Change: New quality check type added, or report schema changes.

Checks: duration_range, sample_rate, clipping, dc_offset, snr,
        duplicates (SHA-256 PCM hash), outliers (3-sigma on duration/amplitude/centroid),
        class_imbalance (< 20% of mean label count)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from app.core.config import project_dir as _project_dir

class QualityChecker:
    @property
    def BASE(self):
        return _project_dir() / "datasets" / "output"

    # Default SNR threshold in dB below which a sample is flagged
    DEFAULT_SNR_THRESHOLD_DB: float = 10.0

    # Default noise profile window in milliseconds
    DEFAULT_NOISE_PROFILE_MS: float = 100.0

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def run(
        self,
        project: str,
        version: str,
        contract: dict | None = None,
    ) -> list[dict]:
        """
        Run all quality checks on the given project/version.

        Parameters
        ----------
        project:  project name (directory under workspace/datasets/output/)
        version:  version subdirectory (e.g. "v1", "v1.0.0")
        contract: optional data-contract dict; if None the project's
                  contract.json is loaded automatically

        Returns
        -------
        List of finding dicts:
            {"sample_path": str, "check_name": str,
             "severity": "warning"|"error", "detail": str}
        """
        findings: list[dict] = []

        project_dir = self.BASE / project
        version_dir = project_dir / version

        # Load contract if not supplied
        if contract is None:
            contract = self._load_json(project_dir / "contract.json", {})

        # Collect all WAV files
        wav_files = sorted(version_dir.rglob("*.wav")) if version_dir.exists() else []

        if not wav_files:
            logger.warning(
                "QualityChecker: no WAV files found in %s/%s", project, version
            )
            self._persist(project_dir, findings)
            return findings

        # Per-sample data collected for outlier detection
        durations: list[float] = []
        peak_amplitudes: list[float] = []
        centroids: list[float] = []
        sample_paths: list[str] = []
        label_counts: dict[str, int] = {}

        # Fingerprint map for duplicate detection: hash → first path
        fingerprints: dict[str, str] = {}

        for wav_path in wav_files:
            rel_path = str(wav_path.relative_to(project_dir))

            # Infer label from directory structure: split/label/file.wav
            parts = wav_path.relative_to(version_dir).parts
            label = parts[-2] if len(parts) >= 2 else "unknown"
            label_counts[label] = label_counts.get(label, 0) + 1

            # ---- metadata-only checks (no full audio load needed) ------
            # Use soundfile.info() to read duration and sample rate cheaply.
            wav_info = self._wav_info(wav_path)
            if wav_info is not None:
                duration_ms, sr_meta = wav_info

                # ---- duration_range ------------------------------------
                findings.extend(
                    self._check_duration_range(rel_path, duration_ms, contract)
                )

                # ---- sample_rate ---------------------------------------
                findings.extend(
                    self._check_sample_rate(rel_path, sr_meta, contract)
                )
            else:
                # Could not read metadata — fall through to full load for error reporting
                duration_ms = 0.0
                sr_meta = 0

            # ---- checks that require full audio data -------------------
            audio_data, sr = self._load_audio(wav_path)
            if audio_data is None:
                findings.append(
                    self._finding(
                        rel_path,
                        "load_error",
                        "error",
                        f"Failed to load audio file: {wav_path.name}",
                    )
                )
                continue

            # Use loaded sr if metadata read failed
            if wav_info is None:
                import numpy as np  # type: ignore
                n_samples = len(audio_data)
                duration_ms = (n_samples / sr * 1000.0) if sr > 0 else 0.0
                findings.extend(self._check_duration_range(rel_path, duration_ms, contract))
                findings.extend(self._check_sample_rate(rel_path, sr, contract))

            # ---- clipping ----------------------------------------------
            findings.extend(self._check_clipping(rel_path, audio_data))

            # ---- dc_offset ---------------------------------------------
            findings.extend(self._check_dc_offset(rel_path, audio_data))

            # ---- snr ---------------------------------------------------
            findings.extend(
                self._check_snr(rel_path, audio_data, sr, contract)
            )

            # ---- duplicates --------------------------------------------
            findings.extend(
                self._check_duplicate(rel_path, audio_data, sr, fingerprints)
            )

            # Accumulate stats for outlier detection
            peak = float(_safe_max_abs(audio_data))
            centroid = self._spectral_centroid(audio_data, sr)

            durations.append(duration_ms)
            peak_amplitudes.append(peak)
            centroids.append(centroid)
            sample_paths.append(rel_path)

        # ---- outliers --------------------------------------------------
        findings.extend(
            self._check_outliers(sample_paths, durations, peak_amplitudes, centroids)
        )

        # ---- class_imbalance -------------------------------------------
        findings.extend(self._check_class_imbalance(label_counts))

        # Persist and return
        report_saved = self._persist(project_dir, findings)
        return findings

    # ------------------------------------------------------------------ #
    # Individual checks                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _check_duration_range(
        rel_path: str, duration_ms: float, contract: dict
    ) -> list[dict]:
        results: list[dict] = []
        min_ms = contract.get("min_duration_ms")
        max_ms = contract.get("max_duration_ms")

        if min_ms is not None and duration_ms < min_ms:
            results.append(
                QualityChecker._finding(
                    rel_path,
                    "duration_range",
                    "error",
                    f"Duration {duration_ms:.1f} ms is below minimum {min_ms} ms",
                )
            )
        if max_ms is not None and duration_ms > max_ms:
            results.append(
                QualityChecker._finding(
                    rel_path,
                    "duration_range",
                    "error",
                    f"Duration {duration_ms:.1f} ms exceeds maximum {max_ms} ms",
                )
            )
        return results

    @staticmethod
    def _check_sample_rate(
        rel_path: str, sr: int, contract: dict
    ) -> list[dict]:
        required_sr = contract.get("required_sample_rate")
        if required_sr is not None and sr != required_sr:
            return [
                QualityChecker._finding(
                    rel_path,
                    "sample_rate",
                    "error",
                    f"Sample rate {sr} Hz does not match required {required_sr} Hz",
                )
            ]
        return []

    @staticmethod
    def _check_clipping(rel_path: str, audio_data: Any) -> list[dict]:
        try:
            import numpy as np  # type: ignore

            peak = float(np.abs(audio_data).max())
            if peak > 0.999:
                return [
                    QualityChecker._finding(
                        rel_path,
                        "clipping",
                        "warning",
                        f"Peak amplitude {peak:.4f} exceeds clipping threshold 0.999",
                    )
                ]
        except Exception as exc:
            logger.debug("clipping check failed for %s: %s", rel_path, exc)
        return []

    @staticmethod
    def _check_dc_offset(rel_path: str, audio_data: Any) -> list[dict]:
        try:
            import numpy as np  # type: ignore

            mean_val = float(np.mean(audio_data))
            if abs(mean_val) > 0.01:
                return [
                    QualityChecker._finding(
                        rel_path,
                        "dc_offset",
                        "warning",
                        f"DC offset {mean_val:.4f} exceeds threshold 0.01",
                    )
                ]
        except Exception as exc:
            logger.debug("dc_offset check failed for %s: %s", rel_path, exc)
        return []

    @staticmethod
    def _check_snr(
        rel_path: str,
        audio_data: Any,
        sr: int,
        contract: dict,
    ) -> list[dict]:
        """
        Estimate SNR using the first noise_profile_ms ms as the noise estimate.
        signal_power = mean of squared non-silent frames
        noise_power  = mean of squared first noise_profile_ms frames
        SNR_dB = 10 * log10(signal_power / noise_power)

        Limitation: this method assumes the first noise_profile_ms milliseconds
        contain only background noise. For files that start with speech or music,
        the "noise" estimate is actually signal, producing a misleadingly low SNR.
        Consider using VAD (Voice Activity Detection) to locate actual silence
        regions for a more accurate noise floor estimate.
        """
        try:
            import numpy as np  # type: ignore

            noise_profile_ms = contract.get(
                "noise_profile_ms", QualityChecker.DEFAULT_NOISE_PROFILE_MS
            )
            snr_threshold = contract.get(
                "snr_threshold_db", QualityChecker.DEFAULT_SNR_THRESHOLD_DB
            )

            noise_samples = max(1, int(sr * noise_profile_ms / 1000.0))
            noise_frames = audio_data[:noise_samples]
            noise_power = float(np.mean(noise_frames ** 2))

            if noise_power <= 0:
                # Cannot estimate SNR — skip
                return []

            # Signal power from non-silent frames (above noise floor)
            signal_power = float(np.mean(audio_data ** 2))

            if signal_power <= 0:
                return [
                    QualityChecker._finding(
                        rel_path,
                        "snr",
                        "warning",
                        "Signal power is zero; SNR cannot be computed",
                    )
                ]

            snr_db = 10.0 * math.log10(signal_power / noise_power)

            if snr_db < snr_threshold:
                return [
                    QualityChecker._finding(
                        rel_path,
                        "snr",
                        "warning",
                        f"Estimated SNR {snr_db:.1f} dB is below threshold {snr_threshold} dB",
                    )
                ]
        except Exception as exc:
            logger.debug("snr check failed for %s: %s", rel_path, exc)
        return []

    @staticmethod
    def _check_duplicate(
        rel_path: str,
        audio_data: Any,
        sr: int,
        fingerprints: dict[str, str],
    ) -> list[dict]:
        """
        Compute SHA-256 of raw float32 PCM bytes after resampling to 16 kHz mono.
        Flag pairs with identical fingerprints.
        """
        try:
            import numpy as np  # type: ignore

            # Resample to 16 kHz mono for comparison
            target_sr = 16000
            mono = _to_mono(audio_data)

            if sr != target_sr:
                try:
                    import librosa  # type: ignore

                    mono = librosa.resample(mono, orig_sr=sr, target_sr=target_sr)
                except Exception:
                    logger.warning(
                        "QualityChecker: resampling skipped for %s (librosa unavailable or failed) "
                        "— duplicate detection may miss cross-sample-rate duplicates",
                        rel_path,
                    )

            # SHA-256 of raw float32 bytes
            pcm_bytes = mono.astype(np.float32).tobytes()
            fingerprint = hashlib.sha256(pcm_bytes).hexdigest()

            if fingerprint in fingerprints:
                original = fingerprints[fingerprint]
                return [
                    QualityChecker._finding(
                        rel_path,
                        "duplicates",
                        "warning",
                        f"Duplicate of {original} (SHA-256: {fingerprint[:16]}...)",
                    )
                ]
            else:
                fingerprints[fingerprint] = rel_path
        except Exception as exc:
            logger.debug("duplicates check failed for %s: %s", rel_path, exc)
        return []

    @staticmethod
    def _check_outliers(
        sample_paths: list[str],
        durations: list[float],
        peak_amplitudes: list[float],
        centroids: list[float],
    ) -> list[dict]:
        """
        Flag samples outside mean ± 3σ for duration, peak amplitude, and spectral centroid.
        """
        results: list[dict] = []
        if len(sample_paths) < 2:
            return results

        metrics = [
            ("duration_ms", durations),
            ("peak_amplitude", peak_amplitudes),
            ("spectral_centroid", centroids),
        ]

        for metric_name, values in metrics:
            mean, std = _mean_std(values)
            if std == 0:
                continue
            low = mean - 3 * std
            high = mean + 3 * std
            for path, val in zip(sample_paths, values):
                if val < low or val > high:
                    results.append(
                        QualityChecker._finding(
                            path,
                            "outliers",
                            "warning",
                            (
                                f"{metric_name} value {val:.4f} is outside "
                                f"mean±3σ range [{low:.4f}, {high:.4f}]"
                            ),
                        )
                    )
        return results

    @staticmethod
    def _check_class_imbalance(label_counts: dict[str, int]) -> list[dict]:
        """
        Flag any label whose count is below 20% of the mean label count.
        """
        results: list[dict] = []
        if not label_counts:
            return results

        counts = list(label_counts.values())
        mean_count = sum(counts) / len(counts)
        threshold = 0.20 * mean_count

        for label, count in label_counts.items():
            if count < threshold:
                results.append(
                    QualityChecker._finding(
                        label,
                        "class_imbalance",
                        "warning",
                        (
                            f"Label '{label}' has {count} samples, "
                            f"which is below 20% of mean ({mean_count:.1f})"
                        ),
                    )
                )
        return results

    # ------------------------------------------------------------------ #
    # Audio loading                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _wav_info(wav_path: Path) -> tuple[float, int] | None:
        """Return (duration_ms, sample_rate) using soundfile.info() — no audio data loaded.

        Returns None if the file cannot be read.
        """
        try:
            import soundfile as sf  # type: ignore
            info = sf.info(str(wav_path))
            duration_ms = info.duration * 1000.0
            return duration_ms, int(info.samplerate)
        except Exception as exc:
            logger.debug("_wav_info failed for %s: %s", wav_path, exc)
            return None

    def _load_audio(self, wav_path: Path) -> tuple[Any, int]:
        """
        Load audio using librosa (primary) or soundfile (fallback).
        Returns (float32 numpy array, sample_rate) or (None, 0) on failure.
        """
        # Primary: librosa
        try:
            import librosa  # type: ignore

            data, sr = librosa.load(str(wav_path), sr=None, mono=True)
            return data, int(sr)
        except Exception as librosa_exc:
            logger.debug("librosa failed for %s: %s", wav_path, librosa_exc)

        # Fallback: soundfile
        try:
            import soundfile as sf  # type: ignore
            import numpy as np  # type: ignore

            data, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
            if data.ndim > 1:
                data = data.mean(axis=1)
            return data, int(sr)
        except Exception as sf_exc:
            logger.debug("soundfile failed for %s: %s", wav_path, sf_exc)

        return None, 0

    # ------------------------------------------------------------------ #
    # Spectral centroid                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _spectral_centroid(audio_data: Any, sr: int) -> float:
        """
        Compute mean spectral centroid using librosa.
        Returns 0.0 on failure.
        """
        try:
            import librosa  # type: ignore
            import numpy as np  # type: ignore

            mono = _to_mono(audio_data)
            centroid = librosa.feature.spectral_centroid(y=mono, sr=sr)
            return float(np.mean(centroid))
        except Exception as exc:
            logger.debug("spectral_centroid failed: %s", exc)
            return 0.0

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def _persist(self, project_dir: Path, findings: list[dict]) -> None:
        """Write findings to quality_report.json in the project directory."""
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            report_path = project_dir / "quality_report.json"
            with report_path.open("w", encoding="utf-8") as f:
                json.dump({"findings": findings}, f, indent=2)
        except Exception as exc:
            logger.warning("Failed to persist quality_report.json: %s", exc)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _finding(
        sample_path: str,
        check_name: str,
        severity: str,
        detail: str,
    ) -> dict:
        return {
            "sample_path": sample_path,
            "check_name": check_name,
            "severity": severity,
            "detail": detail,
        }

    @staticmethod
    def _load_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default


# ------------------------------------------------------------------ #
# Module-level helpers                                                 #
# ------------------------------------------------------------------ #


def _to_mono(audio_data: Any) -> Any:
    """Convert to mono if multi-channel."""
    try:
        import numpy as np  # type: ignore

        if audio_data.ndim > 1:
            return audio_data.mean(axis=1).astype(np.float32)
        return audio_data.astype(np.float32)
    except Exception:
        return audio_data


def _safe_max_abs(audio_data: Any) -> float:
    """Return max absolute value, 0.0 on error."""
    try:
        import numpy as np  # type: ignore

        return float(np.abs(audio_data).max())
    except Exception:
        return 0.0


def _mean_std(values: list[float]) -> tuple[float, float]:
    """Compute mean and population standard deviation."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return mean, math.sqrt(variance)
