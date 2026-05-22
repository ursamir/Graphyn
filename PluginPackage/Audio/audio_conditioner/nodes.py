from __future__ import annotations

import copy
from typing import ClassVar

import librosa
import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample


class AudioConditionerNode(Node):
    """
    Unified production-grade audio preprocessing frontend.

    Performs configurable audio conditioning:
    - DC offset removal
    - mono conversion
    - resampling
    - silence trimming
    - pre-emphasis
    - normalization (peak | rms | lufs)
    - dynamic range compression
    - clipping protection
    - optional batch processing
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="audio_conditioner",
        label="Audio Conditioner",
        description=(
            "Unified audio preprocessing frontend with resampling, "
            "silence trimming, normalization (peak/rms/LUFS), "
            "dynamic range compression, DC offset removal, "
            "pre-emphasis, and clipping protection."
        ),
        category="Preprocessing",
        version="1.1.0",
        tags=[
            "audio",
            "preprocessing",
            "conditioning",
            "frontend",
            "edge-ai",
            "lufs",
            "compression",
        ],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="List of AudioSample objects",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Conditioned AudioSample objects",
        )
    }

    class Config(NodeConfig):
        target_sample_rate: int = 16000

        mono: bool = True

        trim_silence: bool = True
        trim_threshold_db: float = 40.0

        normalize: bool = True
        normalize_method: str = "peak"   # "peak" | "rms" | "lufs"
        target_level_db: float = -1.0
        target_lufs: float = -23.0       # EBU R128 broadcast standard

        remove_dc_offset: bool = True

        preemphasis: bool = False
        preemphasis_coeff: float = 0.97

        # Dynamic range compression (absorbed from compress.py)
        compress: bool = False
        compress_threshold_db: float = -20.0
        compress_ratio: float = 4.0

        limiter: bool = True
        skip_clipped: bool = False

        # 0 = process all at once; N = process in batches of N (chunked iteration,
        # not lazy/generator-based — both paths call _condition_one() per sample)
        batch_size: int = 0

    # ── internal helpers ──────────────────────────────────────────────────────

    def _remove_dc_offset(self, y: np.ndarray) -> np.ndarray:
        return y - np.mean(y)

    def _apply_preemphasis(self, y: np.ndarray, coeff: float) -> np.ndarray:
        return np.concatenate([[y[0]], y[1:] - coeff * y[:-1]])

    def _peak_normalize(self, y: np.ndarray, target_db: float) -> np.ndarray:
        peak = np.max(np.abs(y))
        if peak <= 0:
            return y
        target_amp = 10 ** (target_db / 20.0)
        return y * (target_amp / peak)

    def _rms_normalize(self, y: np.ndarray, target_db: float) -> np.ndarray:
        rms = np.sqrt(np.mean(y ** 2))
        if rms <= 0:
            return y
        target_amp = 10 ** (target_db / 20.0)
        return y * (target_amp / rms)

    def _lufs_normalize(self, y: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
        """ITU-R BS.1770-4 integrated loudness normalization via pyloudnorm."""
        try:
            import pyloudnorm as pyln  # type: ignore
        except ImportError:
            # Graceful fallback to RMS normalization
            import warnings
            warnings.warn(
                "AudioConditionerNode: pyloudnorm not installed — "
                "falling back to RMS normalization. "
                "Install with: pip install pyloudnorm>=0.1"
            )
            return self._rms_normalize(y, self.config.target_level_db)

        meter = pyln.Meter(sr)  # BS.1770-4 meter
        # pyloudnorm expects shape (samples,) or (samples, channels)
        y_2d = y[:, np.newaxis] if y.ndim == 1 else y.T
        try:
            loudness = meter.integrated_loudness(y_2d)
        except Exception:
            return y  # can't measure — return unchanged

        if not np.isfinite(loudness):
            return y  # silence or too short — skip

        gain_db = target_lufs - loudness
        gain_linear = 10 ** (gain_db / 20.0)
        return (y * gain_linear).astype(np.float32)

    def _apply_compression(
        self,
        y: np.ndarray,
        threshold_db: float,
        ratio: float,
    ) -> np.ndarray:
        """Simple feed-forward dynamic range compressor (sample-level).

        Applies gain reduction above threshold_db with the given ratio.
        Attack/release are instantaneous (suitable for offline processing).
        """
        threshold_amp = 10 ** (threshold_db / 20.0)
        abs_y = np.abs(y)
        # Gain reduction factor per sample
        gain = np.where(
            abs_y > threshold_amp,
            threshold_amp * (abs_y / threshold_amp) ** (1.0 / ratio) / np.maximum(abs_y, 1e-9),
            1.0,
        )
        return (y * gain).astype(np.float32)

    # ── single-sample conditioning ────────────────────────────────────────────

    def _condition_one(self, sample: AudioSample) -> AudioSample | None:
        """Condition a single AudioSample. Returns None if sample should be skipped."""
        new_sample = copy.deepcopy(sample)
        y = new_sample.data.astype(np.float32)
        sr = new_sample.sample_rate

        # DC offset removal
        if self.config.remove_dc_offset:
            y = self._remove_dc_offset(y)

        # Convert stereo → mono
        if self.config.mono and y.ndim > 1:
            y = librosa.to_mono(y)

        # Resample
        if sr != self.config.target_sample_rate:
            y = librosa.resample(
                y=y,
                orig_sr=sr,
                target_sr=self.config.target_sample_rate,
            )
            sr = self.config.target_sample_rate

        # Trim silence
        if self.config.trim_silence:
            y, _ = librosa.effects.trim(y, top_db=self.config.trim_threshold_db)

        # Pre-emphasis
        if self.config.preemphasis:
            y = self._apply_preemphasis(y, self.config.preemphasis_coeff)

        # Dynamic range compression
        if self.config.compress:
            y = self._apply_compression(
                y,
                self.config.compress_threshold_db,
                self.config.compress_ratio,
            )

        # Normalize
        if self.config.normalize:
            method = self.config.normalize_method
            if method == "peak":
                y = self._peak_normalize(y, self.config.target_level_db)
            elif method == "rms":
                y = self._rms_normalize(y, self.config.target_level_db)
            elif method == "lufs":
                y = self._lufs_normalize(y, sr, self.config.target_lufs)
            else:
                raise ValueError(
                    f"AudioConditionerNode: unknown normalize_method '{method}'. "
                    "Choose from: peak, rms, lufs"
                )

        # Clipping protection
        clipped = bool(np.any(np.abs(y) > 1.0))
        if clipped:
            if self.config.skip_clipped:
                return None
            if self.config.limiter:
                y = np.clip(y, -1.0, 1.0)

        new_sample.data = y.astype(np.float32)
        new_sample.sample_rate = sr

        new_sample.metadata.update({
            "conditioned": True,
            "conditioning": {
                "sample_rate": sr,
                "mono": self.config.mono,
                "trim_silence": self.config.trim_silence,
                "normalize": self.config.normalize,
                "normalize_method": self.config.normalize_method,
                "target_lufs": self.config.target_lufs if self.config.normalize_method == "lufs" else None,
                "preemphasis": self.config.preemphasis,
                "compress": self.config.compress,
                "output_format": "float32",
            },
            "clipped": clipped,
        })

        return new_sample

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        output: list[AudioSample] = []
        batch_size = self.config.batch_size

        if batch_size <= 0:
            # Process all at once
            for sample in samples:
                result = self._condition_one(sample)
                if result is not None:
                    output.append(result)
        else:
            # Lazy batch processing
            for i in range(0, len(samples), batch_size):
                batch = samples[i:i + batch_size]
                for sample in batch:
                    result = self._condition_one(sample)
                    if result is not None:
                        output.append(result)

        return output
