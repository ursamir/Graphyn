"""SpeakerSeparatorNode — separate speakers or sources from mixed audio.

Backends:
    pyannote    — pyannote.audio diarization + separation
    speechbrain — SpeechBrain SepFormer source separation
    auto        — try pyannote, fall back to speechbrain

output_mode:
    per_speaker      — one AudioSample per detected speaker segment
    diarization_only — original audio with metadata["speaker_segments"] populated
"""
from __future__ import annotations

import copy
import logging
from typing import ClassVar

import numpy as np

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

log = logging.getLogger(__name__)


class SpeakerSeparatorNode(Node):
    """Separate speakers or sources from mixed audio.

    Config:
        backend (str): "pyannote" | "speechbrain" | "auto"
        num_speakers (int): expected number of speakers; 0 = auto-detect
        min_speakers (int): minimum speakers for auto-detection (default 1)
        max_speakers (int): maximum speakers for auto-detection (default 10)
        output_mode (str): "per_speaker" | "diarization_only"
            per_speaker      — emit one AudioSample per speaker segment
            diarization_only — emit original sample with speaker_segments metadata
        auth_token (str): HuggingFace auth token for pyannote models
            (required for pyannote backend; set via env HUGGINGFACE_TOKEN if empty)
        min_segment_s (float): discard speaker segments shorter than this (default 0.5)
    """

    node_type: ClassVar[str] = "speaker_separator"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="speaker_separator",
        label="Speaker Separator",
        description=(
            "Separate speakers from mixed audio via diarization (pyannote.audio) "
            "or source separation (SpeechBrain SepFormer)."
        ),
        category="Enhancement",
        version="1.0.0",
        tags=["audio", "diarization", "speaker", "separation", "pyannote", "speechbrain"],
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
            description="Mixed audio samples to separate",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=list[AudioSample],
            description=(
                "Per-speaker AudioSamples (per_speaker mode) or "
                "original samples with speaker_segments metadata (diarization_only mode)"
            ),
        )
    }

    class Config(NodeConfig):
        backend: str = "auto"           # "pyannote" | "speechbrain" | "auto"
        num_speakers: int = 0           # 0 = auto-detect
        min_speakers: int = 1
        max_speakers: int = 10
        output_mode: str = "per_speaker"  # "per_speaker" | "diarization_only"
        auth_token: str = ""            # HuggingFace token for pyannote
        # WARNING: do not store auth_token in saved pipeline files — use the
        # HUGGINGFACE_TOKEN environment variable instead to avoid secret leakage.
        min_segment_s: float = 0.5      # discard segments shorter than this

    # ── setup ─────────────────────────────────────────────────────────────────

    def setup(self) -> None:
        self._resolved_backend = self._resolve_backend()
        log.debug("SpeakerSeparatorNode: using backend '%s'", self._resolved_backend)

        # Pre-load models once to avoid reloading on every process() call
        self._pyannote_pipeline = None
        self._sepformer_model = None

        import os
        token = self.config.auth_token or os.environ.get("HUGGINGFACE_TOKEN", "")

        if self._resolved_backend == "pyannote":
            try:
                from pyannote.audio import Pipeline as PyannotePipeline  # type: ignore
                self._pyannote_pipeline = PyannotePipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=token or None,
                )
                log.info("SpeakerSeparatorNode: pyannote pipeline loaded")
            except ImportError:
                pass  # handled by _resolve_backend
        elif self._resolved_backend == "speechbrain":
            try:
                from speechbrain.inference.separation import SepformerSeparation  # type: ignore
                self._sepformer_model = SepformerSeparation.from_hparams(
                    source="speechbrain/sepformer-wsj02mix",
                    savedir="pretrained_models/sepformer-wsj02mix",
                )
                log.info("SpeakerSeparatorNode: SepFormer model loaded")
            except ImportError:
                pass  # handled by _resolve_backend

    def _resolve_backend(self) -> str:
        if self.config.backend == "pyannote":
            self._check_pyannote()
            return "pyannote"
        if self.config.backend == "speechbrain":
            self._check_speechbrain()
            return "speechbrain"
        # auto
        try:
            self._check_pyannote()
            return "pyannote"
        except ImportError:
            pass
        try:
            self._check_speechbrain()
            return "speechbrain"
        except ImportError:
            raise ImportError(
                "SpeakerSeparatorNode: no backend available. Install one of:\n"
                "  pip install pyannote.audio>=3.0\n"
                "  pip install speechbrain>=0.5"
            )

    def _check_pyannote(self) -> None:
        try:
            import pyannote.audio  # type: ignore  # noqa: F401
        except ImportError:
            raise ImportError(
                "SpeakerSeparatorNode: 'pyannote.audio' required for backend='pyannote'. "
                "Install with: pip install pyannote.audio>=3.0"
            )

    def _check_speechbrain(self) -> None:
        try:
            import speechbrain  # type: ignore  # noqa: F401
        except ImportError:
            raise ImportError(
                "SpeakerSeparatorNode: 'speechbrain' required for backend='speechbrain'. "
                "Install with: pip install speechbrain>=0.5"
            )

    # ── SISO process ──────────────────────────────────────────────────────────

    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        backend = getattr(self, "_resolved_backend", None) or self._resolve_backend()
        output: list[AudioSample] = []

        for sample in samples:
            if backend == "pyannote":
                results = self._separate_pyannote(sample)
            else:
                results = self._separate_speechbrain(sample)
            output.extend(results)

        return output

    # ── pyannote backend ──────────────────────────────────────────────────────

    def _separate_pyannote(self, sample: AudioSample) -> list[AudioSample]:
        """Diarize using pyannote.audio, then slice audio per speaker segment."""
        import os
        import torch  # type: ignore
        from pyannote.audio import Pipeline as PyannotePipeline  # type: ignore

        # Use cached pipeline from setup(); fall back to loading if needed
        if getattr(self, "_pyannote_pipeline", None) is not None:
            pipeline = self._pyannote_pipeline
        else:
            token = self.config.auth_token or os.environ.get("HUGGINGFACE_TOKEN", "")
            pipeline = PyannotePipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=token or None,
            )

        y = sample.data.astype(np.float32)
        sr = sample.sample_rate

        # pyannote expects a file path or waveform dict
        waveform = torch.from_numpy(y).unsqueeze(0)  # (1, N)
        audio_in = {"waveform": waveform, "sample_rate": sr}

        # Run diarization
        kwargs: dict = {}
        if self.config.num_speakers > 0:
            kwargs["num_speakers"] = self.config.num_speakers
        else:
            kwargs["min_speakers"] = self.config.min_speakers
            kwargs["max_speakers"] = self.config.max_speakers

        diarization = pipeline(audio_in, **kwargs)

        # Collect speaker segments
        speaker_segments: list[dict] = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            speaker_segments.append({
                "speaker_id": speaker,
                "start": turn.start,
                "end": turn.end,
            })

        if self.config.output_mode == "diarization_only":
            new_sample = copy.deepcopy(sample)
            new_sample.metadata["speaker_segments"] = speaker_segments
            new_sample.metadata["speaker_separator"] = {
                "backend": "pyannote",
                "num_segments": len(speaker_segments),
            }
            return [new_sample]

        # per_speaker: slice audio per segment
        return self._slice_segments(sample, speaker_segments, backend="pyannote")

    # ── speechbrain backend ───────────────────────────────────────────────────

    def _separate_speechbrain(self, sample: AudioSample) -> list[AudioSample]:
        """Source separation using SpeechBrain SepFormer."""
        import torch  # type: ignore
        from speechbrain.inference.separation import SepformerSeparation  # type: ignore

        # Use cached model from setup(); fall back to loading if needed
        if getattr(self, "_sepformer_model", None) is not None:
            model = self._sepformer_model
        else:
            model = SepformerSeparation.from_hparams(
                source="speechbrain/sepformer-wsj02mix",
                savedir="pretrained_models/sepformer-wsj02mix",
            )

        # SepFormer wsj02mix separates exactly 2 sources — warn for 3+ speakers
        if self.config.num_speakers > 2:
            log.warning(
                "SpeakerSeparatorNode: speechbrain backend uses sepformer-wsj02mix which "
                "separates exactly 2 sources. num_speakers=%d will be ignored; "
                "remaining speakers will be mixed into the 2 output sources.",
                self.config.num_speakers,
            )

        y = sample.data.astype(np.float32)
        sr = sample.sample_rate

        # SepFormer expects 8kHz mono
        if sr != 8000:
            import librosa  # type: ignore
            y_in = librosa.resample(y=y, orig_sr=sr, target_sr=8000)
            in_sr = 8000
        else:
            y_in = y
            in_sr = sr

        audio_tensor = torch.from_numpy(y_in).unsqueeze(0)  # (1, N)
        est_sources = model.separate_batch(audio_tensor)  # (1, N, num_sources)

        num_sources = est_sources.shape[-1]
        results: list[AudioSample] = []

        for i in range(num_sources):
            src = est_sources[0, :, i].numpy()
            # Resample back to original sr
            if in_sr != sr:
                import librosa  # type: ignore
                src = librosa.resample(y=src, orig_sr=in_sr, target_sr=sr)

            new_sample = copy.deepcopy(sample)
            new_sample.data = src.astype(np.float32)
            new_sample.sample_rate = sr
            new_sample.metadata.update({
                "speaker_id": f"source_{i}",
                "speaker_separator": {
                    "backend": "speechbrain",
                    "source_index": i,
                    "total_sources": num_sources,
                },
            })
            results.append(new_sample)

        return results

    # ── shared: slice audio per diarization segment ───────────────────────────

    def _slice_segments(
        self,
        sample: AudioSample,
        segments: list[dict],
        backend: str,
    ) -> list[AudioSample]:
        """Slice sample.data into per-speaker AudioSamples."""
        y = sample.data
        sr = sample.sample_rate
        min_samples = int(self.config.min_segment_s * sr)
        results: list[AudioSample] = []

        for seg in segments:
            start_s = float(seg["start"])
            end_s = float(seg["end"])
            speaker_id = str(seg.get("speaker_id", "unknown"))

            start_i = int(start_s * sr)
            end_i = min(int(end_s * sr), len(y))
            chunk = y[start_i:end_i]

            if len(chunk) < min_samples:
                continue

            new_sample = copy.deepcopy(sample)
            new_sample.data = chunk.copy().astype(np.float32)
            new_sample.metadata.update({
                "speaker_id": speaker_id,
                "start": start_s,
                "end": end_s,
                "parent": str(sample.path),
                "speaker_separator": {
                    "backend": backend,
                    "output_mode": "per_speaker",
                },
            })
            results.append(new_sample)

        return results
