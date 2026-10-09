"""VoiceConverterNode — any-to-any voice conversion with kNN-VC.

Backends:
    knnvc       — kNN-VC (Baas, van Niekerk & Kamper, Interspeech 2023):
                  WavLM-Large layer-6 features of the source are replaced by
                  their k nearest neighbours from the *target speaker's*
                  reference audio, then vocoded with the prematched HiFi-GAN.
                  Code + weights load once via ``torch.hub`` from
                  ``bshall/knn-vc`` (GitHub release assets). [default]
    pitch_shift — pitch shift only (no identity change). Chosen
                  explicitly; never used as a silent fallback.

``target_speaker`` is required for ``knnvc``: one or more reference audio
files (comma-separated) or a directory of audio files of the target voice.
More reference audio (≥ 1 minute) gives better conversions. Output is 16 kHz
mono. ``pitch_shift_semitones`` is applied after conversion when non-zero.
"""
from __future__ import annotations

import copy
import logging
import threading
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)

_SR = 16000
_AUDIO_EXT = {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".opus"}
_MODEL: dict[str, Any] = {}
_LOCK = threading.Lock()


def _mono(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=np.float32)
    if y.ndim > 1:
        # AudioSample data is (n,) or (n, channels); tolerate (channels, n) too.
        y = y.mean(axis=1) if y.shape[0] >= y.shape[1] else y.mean(axis=0)
    return y


def _to_16k(y: np.ndarray, sr: int) -> np.ndarray:
    y = _mono(y)
    if int(sr) != _SR:
        import librosa  # type: ignore

        y = librosa.resample(y, orig_sr=int(sr), target_sr=_SR)
    return y.astype(np.float32)


def reference_paths(spec: str) -> list[Path]:
    """Resolve ``target_speaker`` (files, comma-separated, or a directory)."""
    paths: list[Path] = []
    for part in [p.strip() for p in (spec or "").split(",") if p.strip()]:
        p = Path(part).expanduser()
        if p.is_dir():
            paths.extend(sorted(q for q in p.rglob("*") if q.suffix.lower() in _AUDIO_EXT))
        elif p.is_file():
            paths.append(p)
        else:
            raise FileNotFoundError(f"VoiceConverterNode: target_speaker reference not found: {part}")
    return paths


def _load_reference(path: Path) -> np.ndarray:
    import soundfile as sf  # type: ignore

    try:
        y, sr = sf.read(str(path), dtype="float32", always_2d=False)
    except Exception:  # formats libsndfile cannot read (m4a, …)
        import librosa  # type: ignore

        y, sr = librosa.load(str(path), sr=None, mono=True)
    return _to_16k(y, sr)


def load_knnvc(device: str = "cpu"):
    """Load (once) the kNN-VC model from torch.hub (bshall/knn-vc, prematched vocoder)."""
    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise RuntimeError("VoiceConverterNode: backend='knnvc' needs torch + torchaudio") from exc
    with _LOCK:
        if device not in _MODEL:
            log.info("VoiceConverterNode: loading kNN-VC (WavLM-Large + prematched HiFi-GAN) on %s", device)
            _MODEL[device] = torch.hub.load(
                "bshall/knn-vc", "knn_vc", prematched=True, trust_repo=True,
                pretrained=True, device=device, verbose=False,
            )
    return _MODEL[device]


class VoiceConverterNode(Node):
    """Convert speech to a target speaker's voice with kNN-VC."""

    node_type: ClassVar[str] = "voice_converter"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="voice_converter",
        label="Voice Converter",
        description=(
            "Any-to-any voice conversion with kNN-VC (WavLM features matched to a "
            "target speaker's reference audio, HiFi-GAN vocoder); optional pitch shift."
        ),
        category="Generation",
        version="2.0.0",
        tags=["audio", "voice-conversion", "knnvc", "wavlm", "timbre", "generative"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=False,
        deterministic=True,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=list[AudioSample],
            cardinality="single",
            required=True,
            description="Source speech samples to convert",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description="Converted speech (16 kHz mono for knnvc)",
        )
    }

    class Config(NodeConfig):
        backend: Literal["knnvc", "pitch_shift"] = Field(
            default="knnvc", title="Backend",
            description="knnvc: convert to the target speaker's voice (kNN-VC). pitch_shift: shift the pitch only (no speaker change).")
        target_speaker: str = Field(
            default="", title="Target speaker reference",
            description="Reference audio of the target voice: file path(s), comma-separated, or a directory. Required for knnvc.")
        topk: int = Field(default=4, ge=1, le=32, title="k (neighbours)",
                          description="Number of nearest target frames averaged per source frame.")
        pitch_shift_semitones: float = Field(
            default=0.0, ge=-24.0, le=24.0, title="Pitch shift (semitones)",
            description="Pitch shift applied after conversion (or alone with backend=pitch_shift).")
        device: Literal["cpu", "cuda", "auto"] = Field(default="cpu", title="Device")

    def setup(self) -> None:
        self._matching_set = None
        self._refs: list[str] = []

    def _device(self) -> str:
        if self.config.device != "auto":
            return self.config.device
        try:
            import torch  # type: ignore

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _get_matching_set(self, vc):
        if getattr(self, "_matching_set", None) is None:
            refs = reference_paths(self.config.target_speaker)
            if not refs:
                raise ValueError(
                    "VoiceConverterNode: backend='knnvc' needs target_speaker = reference audio "
                    "of the target voice (file, comma-separated files, or a directory)")
            import torch  # type: ignore

            tensors = [torch.from_numpy(_load_reference(p)) for p in refs]
            with torch.inference_mode():
                self._matching_set = vc.get_matching_set(tensors, vad_trigger_level=0)
            self._refs = [str(p) for p in refs]
        return self._matching_set

    def _pitch(self, y: np.ndarray, sr: int) -> np.ndarray:
        if abs(self.config.pitch_shift_semitones) < 0.01:
            return y
        import librosa  # type: ignore

        return librosa.effects.pitch_shift(y=y, sr=sr, n_steps=float(self.config.pitch_shift_semitones)).astype(np.float32)

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        cfg = self.config
        if cfg.backend == "pitch_shift" and abs(cfg.pitch_shift_semitones) < 0.01:
            raise ValueError("VoiceConverterNode: backend='pitch_shift' with pitch_shift_semitones=0 does nothing")
        vc = matching = None
        if cfg.backend == "knnvc" and samples:
            if not cfg.target_speaker.strip():
                raise ValueError(
                    "VoiceConverterNode: backend='knnvc' needs target_speaker = reference audio "
                    "of the target voice (file, comma-separated files, or a directory)")
            vc = load_knnvc(self._device())
            matching = self._get_matching_set(vc)

        out: list[AudioSample] = []
        for sample in samples:
            if sample.data is None or len(sample.data) == 0:
                raise ValueError(f"VoiceConverterNode: empty audio in {sample.path}")
            new = copy.deepcopy(sample)
            if cfg.backend == "knnvc":
                import torch  # type: ignore

                src = torch.from_numpy(_to_16k(sample.data, sample.sample_rate))
                with torch.inference_mode():
                    query = vc.get_features(src)
                    wav = vc.match(query, matching, topk=int(cfg.topk))
                y = wav.detach().cpu().numpy().astype(np.float32).reshape(-1)
                sr = _SR
            else:
                y, sr = _mono(sample.data), int(sample.sample_rate)
            y = self._pitch(y, sr)
            peak = float(np.max(np.abs(y))) if y.size else 0.0
            if peak > 1.0:
                y = y / peak
            new.data = y
            new.sample_rate = sr
            new.metadata = dict(new.metadata or {})
            new.metadata["voice_converter"] = {
                "backend": cfg.backend,
                "target_references": list(getattr(self, "_refs", [])) if cfg.backend == "knnvc" else [],
                "topk": int(cfg.topk) if cfg.backend == "knnvc" else None,
                "pitch_shift_semitones": float(cfg.pitch_shift_semitones),
                "sample_rate": sr,
            }
            out.append(new)
        return out
