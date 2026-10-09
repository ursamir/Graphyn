"""AvAlignNode — bridge video to the Audio pack, with A/V offset estimation.

method=extract
    Decode each video's (segment's) audio track with ffmpeg into a 16 kHz
    mono AudioSample, time-aligned to the video by construction.
method=xcorr
    Pair each video with an external recording on the ``audio`` input
    (by index, by file stem, or one recording for all videos), estimate the
    offset between the video's own soundtrack and the recording with
    GCC-PHAT cross-correlation (search ±``max_offset_ms``), and emit the
    recording shifted onto the video timeline. ``offset_ms`` > 0 means the
    recording lags the video. ``confidence`` is the correlation peak over
    the mean absolute correlation (≥ ~5 is a clear match).

Outputs: ``output`` (AvAlignedSample records) and ``audio`` (the aligned
AudioSamples, ready for asr_transcribe, audio_classifier, …).
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

_pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
_types = importlib.import_module(f"{_pkg}.types")
_vio = importlib.import_module(f"{_pkg}._vio")
AvAlignedSample = _types.AvAlignedSample

log = logging.getLogger(__name__)


def gcc_phat(ref: np.ndarray, sig: np.ndarray, sr: int, max_offset_s: float) -> tuple[float, float]:
    """Delay of ``sig`` relative to ``ref`` in seconds (+ = sig lags) and peak/mean confidence."""
    n = len(ref) + len(sig)
    nfft = 1 << (n - 1).bit_length()
    R = np.fft.rfft(ref, nfft)
    S = np.fft.rfft(sig, nfft)
    cross = S * np.conj(R)
    cross /= np.maximum(np.abs(cross), 1e-12)
    cc = np.fft.irfft(cross, nfft)
    max_shift = max(1, min(int(max_offset_s * sr), nfft // 2 - 1))
    cc = np.concatenate([cc[-max_shift:], cc[: max_shift + 1]])
    k = int(np.argmax(np.abs(cc)))
    conf = float(np.abs(cc[k]) / max(np.mean(np.abs(cc)), 1e-12))
    return (k - max_shift) / float(sr), conf


def _mono(y: Any) -> np.ndarray:
    a = np.asarray(y, dtype=np.float32)
    if a.ndim > 1:
        a = a.mean(axis=1) if a.shape[0] >= a.shape[1] else a.mean(axis=0)
    return a


def _resample(y: np.ndarray, sr: int, target: int) -> np.ndarray:
    if int(sr) == int(target):
        return y
    from math import gcd

    from scipy.signal import resample_poly  # type: ignore

    g = gcd(int(sr), int(target))
    return resample_poly(y, int(target) // g, int(sr) // g).astype(np.float32)


class AvAlignNode(Node):
    """Extract or cross-correlation-align audio for video segments."""

    node_type: ClassVar[str] = "av_align"
    _siso: ClassVar[bool] = False

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="av_align",
        label="A/V Align",
        description="Extract a video's audio as AudioSamples, or align an external recording to the video with GCC-PHAT (offset + confidence).",
        category="Processing",
        version="1.0.0",
        tags=["video", "audio", "alignment", "sync", "gcc-phat"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "video": InputPort(name="video", data_type=list, cardinality="single", required=True,
                           description="list[VideoSample] (videos or clips)"),
        "audio": InputPort(name="audio", data_type=list | None, cardinality="single", required=False,
                           description="list[AudioSample] external recordings (method=xcorr)"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[AvAlignedSample], description="Alignment records"),
        "audio": OutputPort(name="audio", data_type=list[AudioSample], description="Audio aligned to each video segment"),
    }

    class Config(NodeConfig):
        method: Literal["extract", "xcorr"] = Field(default="extract", title="Method")
        sample_rate: int = Field(default=16000, ge=8000, le=48000, title="Sample rate")
        max_offset_ms: int = Field(default=500, ge=1, le=60000, title="Max offset (ms)", description="xcorr search range ±.")
        min_confidence: float = Field(default=0.0, ge=0, title="Min confidence",
                                      description="xcorr: fail when the peak/mean confidence is below this (0 = never).")

    def _pair(self, videos: list, audios: list) -> list[tuple[Any, Any]]:
        if not audios:
            raise ValueError("AvAlignNode: method=xcorr needs recordings on the 'audio' input")
        if len(audios) == 1:
            return [(v, audios[0]) for v in videos]
        if len(audios) == len(videos):
            return list(zip(videos, audios))
        by_stem = {Path(str(_vio.get(a, "path", "") or "")).stem: a for a in audios}
        pairs = []
        for v in videos:
            stem = Path(str(_vio.get(v, "source_path", "") or _vio.media_path(v))).stem
            if stem not in by_stem:
                raise ValueError(f"AvAlignNode: no recording matches video {stem!r} (pair by index, stem, or pass one recording)")
            pairs.append((v, by_stem[stem]))
        return pairs

    def process(self, inputs: dict) -> dict:
        cfg = self.config
        sr = int(cfg.sample_rate)
        videos = _vio.as_list(inputs.get("video"))
        records: list = []
        audio_out: list = []
        pairs = [(v, None) for v in videos] if cfg.method == "extract" else self._pair(videos, _vio.as_list(inputs.get("audio")))
        for video, rec in pairs:
            path = _vio.media_path(video)
            start, end = _vio.span(video)
            info = _vio.probe(path)
            if end is None:
                end = start + info["duration_s"]
            label = str(_vio.get(video, "label", "") or "")
            if not info["has_audio"]:
                raise ValueError(f"AvAlignNode: {path} has no audio track (method={cfg.method} needs one)")
            track = _vio.audio_pcm(path, sample_rate=sr, start=start, end=end)
            offset_s, conf, audio_path = 0.0, 1.0, path
            y = track
            if cfg.method == "xcorr":
                ext = _resample(_mono(_vio.get(rec, "data")), int(_vio.get(rec, "sample_rate", sr)), sr)
                audio_path = str(_vio.get(rec, "path", "") or "")
                offset_s, conf = gcc_phat(track, ext, sr, cfg.max_offset_ms / 1000.0)
                if cfg.min_confidence and conf < cfg.min_confidence:
                    raise ValueError(f"AvAlignNode: low alignment confidence {conf:.2f} < {cfg.min_confidence} for {path}")
                shift = int(round(offset_s * sr))
                y = ext[shift:] if shift >= 0 else np.concatenate([np.zeros(-shift, np.float32), ext])
                y = y[: len(track)]
                if len(y) < len(track):
                    y = np.concatenate([y, np.zeros(len(track) - len(y), np.float32)])
            meta = {"av_align": {"method": cfg.method, "video_path": path, "start_s": round(start, 3),
                                 "end_s": round(end, 3), "offset_ms": round(offset_s * 1000.0, 2),
                                 "confidence": round(conf, 3)}}
            audio_out.append(AudioSample(path=f"{audio_path}#t={start:.3f},{end:.3f}", sample_rate=sr,
                                         data=y.astype(np.float32), label=label, metadata=meta))
            records.append(AvAlignedSample(video_path=path, audio_path=audio_path, start_s=round(start, 3),
                                           end_s=round(end, 3), method=cfg.method,
                                           offset_ms=round(offset_s * 1000.0, 2), confidence=round(conf, 3),
                                           label=label, metadata={"n_samples": int(len(y)), "sample_rate": sr}))
        return {"output": records, "audio": audio_out}
