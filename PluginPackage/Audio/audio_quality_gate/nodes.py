"""AudioQualityGateNode — dataset quality validation.

Validates audio samples against configurable quality thresholds:
SNR, clipping, silence, loudness (LUFS), bandwidth, and duration.

Absorbs: duration_filter.py (duration check), command_validator.py (duration + action logic).
"""
from __future__ import annotations

import logging
from typing import ClassVar

import librosa
import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)

_SampleList = list[AudioSample]


class AudioQualityGateNode(Node):
    """Dataset quality validation: SNR, clipping, silence, loudness, bandwidth, duration.

    Each sample is run through all enabled checks. Samples that fail any check
    are routed to the ``rejected`` output port with rejection reasons stored in
    ``sample.metadata["quality_rejection_reasons"]``.

    Samples that pass all checks are routed to the ``output`` port with quality
    scores stored in ``sample.metadata["quality"]``.

    Config:
        min_snr_db (float): Minimum acceptable SNR in dB. Default: 10.0.
        max_clipping_ratio (float): Max fraction of clipped samples (|amp| >= 0.99). Default: 0.01.
        min_duration_s (float): Minimum duration in seconds. Default: 0.1.
        max_duration_s (float): Maximum duration in seconds. Default: 60.0.
        min_lufs (float): Minimum integrated loudness in LUFS. Default: -70.0.
        max_lufs (float): Maximum integrated loudness in LUFS. Default: -10.0.
        min_bandwidth_hz (float): Minimum spectral rolloff (85% energy) in Hz. Default: 1000.0.
        rejection_policy (str): What to do with rejected samples:
            "skip" — route to rejected port silently (default)
            "warn" — log a warning and route to rejected port
            "raise" — raise ValueError immediately
        check_snr (bool): Enable SNR check. Default: True.
        check_clipping (bool): Enable clipping check. Default: True.
        check_silence (bool): Enable RMS-below-threshold silence check. Default: True.
        silence_rms_threshold (float): RMS below this is considered silent. Default: 0.001.
        check_duration (bool): Enable duration check. Default: True.
        check_lufs (bool): Enable LUFS check (requires pyloudnorm). Default: False.
        check_bandwidth (bool): Enable bandwidth check. Default: True.
    """

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="audio_quality_gate",
        label="Audio Quality Gate",
        description="Dataset quality validation: SNR, clipping, silence, loudness, bandwidth, duration.",
        category="Validation",
        version="1.0.0",
        tags=["audio", "quality", "validation", "preprocessing"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=_SampleList,
            cardinality="single",
            required=True,
            description="List of AudioSample objects to validate.",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=_SampleList,
            description="Validated AudioSample objects that passed all quality checks.",
        ),
        "rejected": OutputPort(
            name="rejected",
            data_type=_SampleList,
            description="Rejected AudioSample objects with rejection reasons in metadata.",
        ),
    }

    class Config(NodeConfig):
        min_snr_db: float = 10.0
        max_clipping_ratio: float = 0.01
        min_duration_s: float = 0.1
        max_duration_s: float = 60.0
        min_lufs: float = -70.0
        max_lufs: float = -10.0
        min_bandwidth_hz: float = 1000.0
        rejection_policy: str = "skip"   # "skip" | "warn" | "raise"
        check_snr: bool = True
        check_clipping: bool = True
        check_silence: bool = True       # RMS-below-threshold silence check
        silence_rms_threshold: float = 0.001  # RMS below this → rejected as silent
        check_duration: bool = True
        check_lufs: bool = False          # requires pyloudnorm
        check_bandwidth: bool = True

    # ── multi-port process ────────────────────────────────────────────────────

    def process(self, inputs: dict) -> dict:
        """Route each sample to output (passed) or rejected based on quality checks."""
        if isinstance(inputs, list):
            samples = inputs
        elif isinstance(inputs, dict):
            samples = inputs.get("input") or []
        else:
            samples = []
        passed = []
        rejected = []

        for sample in samples:
            reasons = self._check_sample(sample)
            quality_scores = self._compute_quality_metadata(sample)
            if reasons:
                sample.metadata["quality_rejection_reasons"] = reasons
                sample.metadata["quality_passed"] = False
                sample.metadata["quality"] = quality_scores
                if self.config.rejection_policy == "raise":
                    raise ValueError(
                        f"AudioQualityGateNode: sample '{sample.path}' rejected: {reasons}"
                    )
                elif self.config.rejection_policy == "warn":
                    log.warning(
                        "AudioQualityGateNode: sample '%s' rejected: %s",
                        sample.path,
                        reasons,
                    )
                    rejected.append(sample)
                else:  # "skip"
                    rejected.append(sample)
            else:
                sample.metadata["quality_passed"] = True
                sample.metadata["quality"] = quality_scores
                passed.append(sample)

        log.debug(
            "AudioQualityGateNode: %d samples → %d passed, %d rejected",
            len(samples),
            len(passed),
            len(rejected),
        )

        return {"output": passed, "rejected": rejected}

    # ── individual quality checks ─────────────────────────────────────────────

    def _check_duration(self, sample: AudioSample) -> str | None:
        """Reject samples outside the configured duration range."""
        if sample.data is None:
            return "no_data (data is None)"
        if not sample.sample_rate or sample.sample_rate <= 0:
            return f"invalid_sample_rate (sample_rate={sample.sample_rate})"
        duration = len(sample.data) / sample.sample_rate
        if duration < self.config.min_duration_s:
            return f"too_short ({duration:.3f}s < {self.config.min_duration_s}s)"
        if duration > self.config.max_duration_s:
            return f"too_long ({duration:.3f}s > {self.config.max_duration_s}s)"
        return None

    def _check_clipping(self, sample: AudioSample) -> str | None:
        """Reject samples with too many clipped samples (|amplitude| >= 0.99)."""
        clipping_ratio = float(np.mean(np.abs(sample.data) >= 0.99))
        if clipping_ratio > self.config.max_clipping_ratio:
            return f"clipping ({clipping_ratio:.4f} > {self.config.max_clipping_ratio})"
        return None

    def _check_silence(self, sample: AudioSample) -> str | None:
        """Reject samples whose RMS energy is below the silence threshold."""
        rms = float(np.sqrt(np.mean(sample.data ** 2)))
        if rms < self.config.silence_rms_threshold:
            return f"silent (rms={rms:.6f} < threshold={self.config.silence_rms_threshold})"
        return None

    def _check_snr(self, sample: AudioSample) -> str | None:
        """Estimate SNR using the 5th-percentile amplitude as the noise floor proxy.

        This is more robust than assuming the first 10ms is noise — it works
        correctly even when audio starts with speech.
        Returns None (no rejection) if the noise floor is essentially silent.

        Limitation: this heuristic can produce inaccurate estimates for audio
        with non-stationary noise (e.g. music with quiet passages, or a single
        loud click followed by silence). In such cases the 5th-percentile of
        |data| is near zero, so noise_power < 1e-10 and the check is skipped.
        For production use, consider a proper noise estimation algorithm
        (e.g. minimum statistics or NIST STNR).
        """
        abs_data = np.abs(sample.data)
        noise_floor = float(np.percentile(abs_data, 5))
        signal_power = float(np.mean(sample.data ** 2))
        noise_power = noise_floor ** 2
        if noise_power < 1e-10:
            return None  # essentially silent noise floor — can't estimate SNR
        snr_db = 10 * np.log10(max(signal_power / noise_power, 1e-10))
        if snr_db < self.config.min_snr_db:
            return f"low_snr ({snr_db:.1f}dB < {self.config.min_snr_db}dB)"
        return None

    def _check_bandwidth(self, sample: AudioSample) -> str | None:
        """Reject samples with insufficient spectral bandwidth (rolloff at 85% energy)."""
        if sample.data is None or len(sample.data) == 0:
            return "empty_audio (zero samples)"
        rolloff = librosa.feature.spectral_rolloff(
            y=sample.data, sr=sample.sample_rate, roll_percent=0.85
        )
        mean_rolloff = float(np.mean(rolloff))
        if mean_rolloff < self.config.min_bandwidth_hz:
            return f"narrow_bandwidth ({mean_rolloff:.0f}Hz < {self.config.min_bandwidth_hz}Hz)"
        return None

    def _check_lufs(self, sample: AudioSample) -> str | None:
        """Reject samples outside the configured LUFS loudness range.

        Requires pyloudnorm. Skips gracefully if not installed.
        """
        try:
            import pyloudnorm as pyln  # type: ignore
        except ImportError:
            log.debug("AudioQualityGateNode: pyloudnorm not installed, skipping LUFS check")
            return None

        meter = pyln.Meter(sample.sample_rate)
        try:
            loudness = meter.integrated_loudness(sample.data)
        except (ValueError, RuntimeError):
            return None  # audio too short or invalid for BS.1770 gating

        if loudness < self.config.min_lufs:
            return f"too_quiet ({loudness:.1f} LUFS < {self.config.min_lufs} LUFS)"
        if loudness > self.config.max_lufs:
            return f"too_loud ({loudness:.1f} LUFS > {self.config.max_lufs} LUFS)"
        return None

    def _check_sample(self, sample: AudioSample) -> list[str]:
        """Run all enabled checks and return a list of rejection reasons."""
        reasons: list[str] = []

        if self.config.check_duration:
            r = self._check_duration(sample)
            if r:
                reasons.append(r)

        if self.config.check_clipping:
            r = self._check_clipping(sample)
            if r:
                reasons.append(r)

        if self.config.check_silence:
            r = self._check_silence(sample)
            if r:
                reasons.append(r)

        if self.config.check_snr:
            r = self._check_snr(sample)
            if r:
                reasons.append(r)

        if self.config.check_bandwidth:
            r = self._check_bandwidth(sample)
            if r:
                reasons.append(r)

        if self.config.check_lufs:
            r = self._check_lufs(sample)
            if r:
                reasons.append(r)

        return reasons

    def _compute_quality_metadata(self, sample: AudioSample) -> dict:
        """Compute and return quality scores for samples that passed all checks."""
        duration = (len(sample.data) / sample.sample_rate) if sample.data is not None and sample.sample_rate else 0.0
        clipping_ratio = float(np.mean(np.abs(sample.data) >= 0.99)) if sample.data is not None else 0.0
        rms = float(np.sqrt(np.mean(sample.data ** 2))) if sample.data is not None else 0.0
        return {
            "duration_s": duration,
            "clipping_ratio": clipping_ratio,
            "rms": rms,
        }
