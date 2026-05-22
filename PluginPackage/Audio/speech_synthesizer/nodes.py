"""SpeechSynthesizerNode — text-to-speech and neural speech generation.

Backends:
    coqui   — Coqui TTS (TTS library, multilingual, voice cloning)
    espeak  — eSpeak NG (lightweight, no GPU, always available via subprocess)
    auto    — try coqui, fall back to espeak
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


class SpeechSynthesizerNode(Node):
    """Text-to-speech and neural speech generation.

    Accepts a list of text strings and produces a list of AudioSample objects.

    Config:
        backend (str): "coqui" | "espeak" | "auto"
        model_name (str): Coqui TTS model name (default: tts_models/en/ljspeech/tacotron2-DDC)
        language (str): BCP-47 language code (default "en")
        speaker (str): speaker ID for multi-speaker models (empty = default speaker)
        reference_audio (str): path to reference audio for voice cloning (Coqui XTTS)
        sample_rate (int): output sample rate in Hz (default 22050)
        speed (float): speech rate multiplier (default 1.0)
    """

    node_type: ClassVar[str] = "speech_synthesizer"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="speech_synthesizer",
        label="Speech Synthesizer",
        description=(
            "Text-to-speech synthesis via Coqui TTS (neural, multilingual, voice cloning) "
            "or eSpeak NG (lightweight fallback)."
        ),
        category="Generation",
        version="1.0.0",
        tags=["audio", "tts", "synthesis", "coqui", "espeak", "voice-cloning", "generative"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=False,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list,
            cardinality="single",
            required=True,
            description="List of text strings to synthesize",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Synthesized AudioSample objects",
        )
    }

    class Config(NodeConfig):
        backend: str = "auto"           # "coqui" | "espeak" | "auto"
        model_name: str = "tts_models/en/ljspeech/tacotron2-DDC"
        language: str = "en"
        speaker: str = ""               # speaker ID for multi-speaker models
        reference_audio: str = ""       # path to reference audio for voice cloning
        sample_rate: int = 22050
        speed: float = 1.0

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, texts: list) -> list[AudioSample]:
        backend = self._resolve_backend()
        output: list[AudioSample] = []

        for i, text in enumerate(texts):
            text_str = str(text).strip()
            if not text_str:
                continue

            if backend == "coqui":
                audio_data, sr = self._synthesize_coqui(text_str)
            else:
                audio_data, sr = self._synthesize_espeak(text_str)

            # Resample to the configured sample_rate if needed
            target_sr = self.config.sample_rate
            if sr != target_sr and len(audio_data) > 0:
                import librosa  # type: ignore
                audio_data = librosa.resample(
                    y=audio_data.astype(np.float32),
                    orig_sr=sr,
                    target_sr=target_sr,
                )
                sr = target_sr

            output.append(AudioSample(
                path=f"synthesized_{i}.wav",
                sample_rate=sr,
                data=audio_data.astype(np.float32),
                label="synthesized",
                metadata={
                    "speech_synthesizer": {
                        "backend": backend,
                        "text": text_str[:100],
                        "language": self.config.language,
                        "model": self.config.model_name if backend == "coqui" else "espeak",
                        "speaker": self.config.speaker or "default",
                    }
                },
            ))

        return output

    def _resolve_backend(self) -> str:
        if self.config.backend == "coqui":
            return "coqui"
        if self.config.backend == "espeak":
            return "espeak"
        # auto: try coqui first
        try:
            from TTS.api import TTS  # type: ignore  # noqa: F401
            return "coqui"
        except ImportError:
            return "espeak"

    # ── Coqui TTS backend ─────────────────────────────────────────────────────

    def _synthesize_coqui(self, text: str) -> tuple[np.ndarray, int]:
        try:
            from TTS.api import TTS  # type: ignore
        except ImportError:
            raise ImportError(
                "SpeechSynthesizerNode: 'TTS' (Coqui) required for backend='coqui'. "
                "Install with: pip install TTS>=0.22"
            )

        if not hasattr(self, "_tts_model"):
            self._tts_model = TTS(model_name=self.config.model_name, progress_bar=False)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name

        try:
            kwargs: dict = {"text": text, "file_path": out_path}
            if self.config.speaker:
                kwargs["speaker"] = self.config.speaker
            if self.config.reference_audio and Path(self.config.reference_audio).exists():
                kwargs["speaker_wav"] = self.config.reference_audio
                kwargs["language"] = self.config.language

            self._tts_model.tts_to_file(**kwargs)

            import soundfile as sf  # type: ignore
            audio_data, sr = sf.read(out_path, dtype="float32")
        finally:
            Path(out_path).unlink(missing_ok=True)

        if audio_data.ndim > 1:
            audio_data = audio_data[:, 0]

        return audio_data, sr

    # ── eSpeak NG backend ─────────────────────────────────────────────────────

    def _synthesize_espeak(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize via eSpeak NG subprocess → WAV → numpy."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name

        cmd = [
            "espeak-ng",
            "-v", self.config.language,
            "-s", str(int(175 * self.config.speed)),  # words per minute
            "-w", out_path,
            text,
        ]

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise RuntimeError(f"eSpeak NG failed: {result.stderr}")
        except FileNotFoundError:
            raise ImportError(
                "SpeechSynthesizerNode: 'espeak-ng' not found. "
                "Install with: sudo apt-get install espeak-ng  "
                "or: brew install espeak"
            )

        try:
            try:
                import soundfile as sf  # type: ignore
                audio_data, sr = sf.read(out_path, dtype="float32")
            except Exception:
                import wave
                with wave.open(out_path, "rb") as wf:
                    sr = wf.getframerate()
                    frames = wf.readframes(wf.getnframes())
                    audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        finally:
            Path(out_path).unlink(missing_ok=True)

        if isinstance(audio_data, np.ndarray) and audio_data.ndim > 1:
            audio_data = audio_data[:, 0]

        return audio_data, sr
