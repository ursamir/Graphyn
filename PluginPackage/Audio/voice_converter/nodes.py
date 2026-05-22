"""VoiceConverterNode — transform speaker identity or vocal style.

Backends:
    speechbrain — SpeechBrain voice conversion (timbre transfer)
    knnvc       — kNN-VC voice conversion (any-to-any, no training needed)
    auto        — try speechbrain, fall back to knnvc
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


class VoiceConverterNode(Node):
    """Transform speaker identity or vocal style.

    Config:
        backend (str): "speechbrain" | "knnvc" | "auto"
        conversion_type (str): "timbre" | "accent" | "gender" | "style"
        target_speaker (str): target speaker ID or path to reference audio
        pitch_shift_semitones (float): additional pitch shift in semitones (default 0.0)
    """

    node_type: ClassVar[str] = "voice_converter"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="voice_converter",
        label="Voice Converter",
        description=(
            "Transform speaker identity or vocal style via SpeechBrain or kNN-VC. "
            "Supports timbre, accent, gender, and style conversion."
        ),
        category="Generation",
        version="1.0.0",
        tags=["audio", "voice-conversion", "speechbrain", "knnvc", "timbre", "generative"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=False,
        cacheable=False,
        streaming_support=False,
        realtime_support=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="Source audio samples to convert",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Voice-converted audio samples",
        )
    }

    class Config(NodeConfig):
        backend: str = "auto"               # "speechbrain" | "knnvc" | "auto"
        conversion_type: str = "timbre"     # "timbre" | "accent" | "gender" | "style"
        # NOTE: conversion_type is stored in metadata for lineage tracking.
        # Backend-specific conversion behaviour per type is reserved for future implementation.
        target_speaker: str = ""            # speaker ID or reference audio path
        pitch_shift_semitones: float = 0.0  # additional pitch shift

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        backend = self._resolve_backend()
        output: list[AudioSample] = []

        for sample in samples:
            new_sample = copy.deepcopy(sample)

            if backend == "speechbrain":
                new_sample = self._convert_speechbrain(new_sample)
            elif backend == "knnvc":
                new_sample = self._convert_knnvc(new_sample)
            else:
                new_sample = self._convert_pitch_only(new_sample)

            new_sample.metadata["voice_converter"] = {
                "backend": backend,
                "conversion_type": self.config.conversion_type,
                "target_speaker": self.config.target_speaker or "default",
                "pitch_shift_semitones": self.config.pitch_shift_semitones,
            }
            output.append(new_sample)

        return output

    def _resolve_backend(self) -> str:
        if self.config.backend == "speechbrain":
            return "speechbrain"
        if self.config.backend == "knnvc":
            return "knnvc"
        # auto
        try:
            import speechbrain  # type: ignore  # noqa: F401
            return "speechbrain"
        except ImportError:
            pass
        try:
            import knnvc  # type: ignore  # noqa: F401
            return "knnvc"
        except ImportError:
            pass
        log.warning(
            "VoiceConverterNode: no conversion backend available — "
            "applying pitch shift only. Install speechbrain or knnvc."
        )
        return "pitch_only"

    # ── SpeechBrain backend ───────────────────────────────────────────────────

    def _convert_speechbrain(self, sample: AudioSample) -> AudioSample:
        try:
            import torch  # type: ignore
            from speechbrain.inference.vocoders import HifiGanVocoder  # type: ignore
            from speechbrain.inference.conversion import VoiceConversion  # type: ignore
        except ImportError:
            raise ImportError(
                "VoiceConverterNode: 'speechbrain' required for backend='speechbrain'. "
                "Install with: pip install speechbrain>=0.5"
            )

        if not hasattr(self, "_vc_model"):
            self._vc_model = VoiceConversion.from_hparams(
                source="speechbrain/voice-conversion-vctk-coqui-tts",
                savedir="pretrained_models/voice_conversion",
            )

        y = sample.data.astype(np.float32)
        sr = sample.sample_rate

        # Resample to 16kHz for SpeechBrain
        if sr != 16000:
            import librosa  # type: ignore
            y = librosa.resample(y=y, orig_sr=sr, target_sr=16000)
            sr = 16000

        wav_tensor = torch.from_numpy(y).unsqueeze(0)

        # Load target speaker reference if provided
        target_wav = None
        if self.config.target_speaker and Path(self.config.target_speaker).exists():
            import soundfile as sf  # type: ignore
            t_data, t_sr = sf.read(self.config.target_speaker, dtype="float32")
            if t_sr != 16000:
                import librosa  # type: ignore
                t_data = librosa.resample(y=t_data, orig_sr=t_sr, target_sr=16000)
            target_wav = torch.from_numpy(t_data).unsqueeze(0)

        with torch.no_grad():
            if target_wav is not None:
                converted = self._vc_model.convert_voice(wav_tensor, target_wav)
            else:
                converted = self._vc_model.convert_voice(wav_tensor, wav_tensor)

        y_out = converted.squeeze().numpy()

        # Apply additional pitch shift if requested
        if abs(self.config.pitch_shift_semitones) > 0.01:
            import librosa  # type: ignore
            y_out = librosa.effects.pitch_shift(y=y_out, sr=sr, n_steps=self.config.pitch_shift_semitones)

        sample.data = y_out.astype(np.float32)
        sample.sample_rate = sr
        return sample

    # ── kNN-VC backend ────────────────────────────────────────────────────────

    def _convert_knnvc(self, sample: AudioSample) -> AudioSample:
        try:
            import knnvc  # type: ignore
        except ImportError:
            raise ImportError(
                "VoiceConverterNode: 'knnvc' required for backend='knnvc'. "
                "Install with: pip install knnvc>=0.1"
            )

        y = sample.data.astype(np.float32)
        sr = sample.sample_rate

        target_path = self.config.target_speaker
        if not target_path or not Path(target_path).exists():
            log.warning("VoiceConverterNode: no target_speaker path — using pitch shift only")
            return self._convert_pitch_only(sample)

        y_out = knnvc.convert(y, sr, target_path)
        sample.data = np.asarray(y_out, dtype=np.float32)
        return sample

    # ── pitch-only fallback ───────────────────────────────────────────────────

    def _convert_pitch_only(self, sample: AudioSample) -> AudioSample:
        """Fallback: apply pitch shift only when no backend is available."""
        if abs(self.config.pitch_shift_semitones) < 0.01:
            return sample
        import librosa  # type: ignore
        y_out = librosa.effects.pitch_shift(
            y=sample.data.astype(np.float32),
            sr=sample.sample_rate,
            n_steps=self.config.pitch_shift_semitones,
        )
        sample.data = y_out.astype(np.float32)
        return sample
