"""VideoQualityGateNode — accept/reject videos on measurable quality checks.

Checks (each can be disabled): duration range, minimum resolution and fps,
audio presence, and — measured by one ffmpeg pass per video — the fraction
of time that is black (``blackdetect``), frozen (``freezedetect``) or
silent (``silencedetect``). Every sample gets ``metadata["quality"]`` with
the measurements and the reasons it failed.

rejection_policy: ``skip`` routes failures to the ``rejected`` port;
``flag`` passes everything through with the verdict recorded; ``fail``
raises when any video fails.
"""
from __future__ import annotations

import importlib
import logging
import re
from typing import Any, ClassVar, Literal

from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

_pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
_types = importlib.import_module(f"{_pkg}.types")
_vio = importlib.import_module(f"{_pkg}._vio")
VideoSample = _types.VideoSample

log = logging.getLogger(__name__)

_BLACK = re.compile(r"black_duration:\s*([0-9.]+)")
_FREEZE = re.compile(r"freeze_duration:\s*([0-9.]+)")
_SILENCE = re.compile(r"silence_duration:\s*([0-9.]+)")


def _to_sample(item: Any) -> Any:
    if isinstance(item, VideoSample):
        return item.model_copy(deep=True)
    if isinstance(item, dict):
        fields = VideoSample.model_fields
        return VideoSample(**{k: v for k, v in item.items() if k in fields})
    if hasattr(item, "model_dump"):
        return _to_sample(item.model_dump())
    return VideoSample(path=_vio.media_path(item))


class VideoQualityGateNode(Node):
    """Gate videos on duration/resolution/fps/audio and black/frozen/silent ratios."""

    node_type: ClassVar[str] = "video_quality_gate"
    _siso: ClassVar[bool] = False

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="video_quality_gate",
        label="Video Quality Gate",
        description="Reject videos that are too short/long, low-res, low-fps, missing audio, or mostly black/frozen/silent (ffmpeg blackdetect/freezedetect/silencedetect).",
        category="Processing",
        version="1.0.0",
        tags=["video", "quality", "gate", "ffmpeg"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list, cardinality="single", required=True,
                           description="list[VideoSample] (from video_ingest / clip_segment)"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[VideoSample], description="Videos that passed (all videos with policy=flag)"),
        "rejected": OutputPort(name="rejected", data_type=list[VideoSample], description="Videos that failed (policy=skip)"),
    }

    class Config(NodeConfig):
        min_duration_s: float = Field(default=0.5, ge=0, title="Min duration (s)")
        max_duration_s: float = Field(default=3600.0, ge=0, title="Max duration (s)", description="0 = no maximum.")
        min_width: int = Field(default=0, ge=0, title="Min width (px)")
        min_height: int = Field(default=0, ge=0, title="Min height (px)")
        min_fps: float = Field(default=0.0, ge=0, title="Min fps")
        require_audio: bool = Field(default=False, title="Require audio track")
        max_black_ratio: float = Field(default=0.5, ge=0, le=1, title="Max black ratio",
                                       description="Max fraction of duration that is black (1 = don't measure).")
        max_frozen_ratio: float = Field(default=1.0, ge=0, le=1, title="Max frozen ratio",
                                        description="Max fraction of duration that is frozen (1 = don't measure).")
        max_silence_ratio: float = Field(default=1.0, ge=0, le=1, title="Max silence ratio",
                                         description="Max fraction of duration that is silent (1 = don't measure).")
        rejection_policy: Literal["skip", "flag", "fail"] = Field(default="skip", title="Rejection policy")

    def _measure(self, s: Any) -> dict[str, float]:
        cfg = self.config
        want_black = cfg.max_black_ratio < 1.0
        want_freeze = cfg.max_frozen_ratio < 1.0
        want_silence = cfg.max_silence_ratio < 1.0 and s.has_audio
        if not (want_black or want_freeze or want_silence):
            return {}
        start, end = _vio.span(s)
        args = ["-ss", f"{start:.3f}"]
        if end is not None:
            args += ["-to", f"{end:.3f}"]
        args += ["-i", s.path]
        vf = []
        if want_black:
            vf.append("blackdetect=d=0.1:pix_th=0.10")
        if want_freeze:
            vf.append("freezedetect=n=-60dB:d=1")
        if vf:
            args += ["-vf", ",".join(vf)]
        else:
            args += ["-vn"]
        if want_silence:
            args += ["-af", "silencedetect=n=-50dB:d=0.5"]
        else:
            args += ["-an"]
        args += ["-f", "null", "-"]
        log_text = _vio.run_stderr(args)
        dur = max(1e-6, float(s.duration_s or 0.0))
        m: dict[str, float] = {}
        if want_black:
            m["black_ratio"] = round(min(1.0, sum(float(x) for x in _BLACK.findall(log_text)) / dur), 4)
        if want_freeze:
            m["frozen_ratio"] = round(min(1.0, sum(float(x) for x in _FREEZE.findall(log_text)) / dur), 4)
        if want_silence:
            m["silence_ratio"] = round(min(1.0, sum(float(x) for x in _SILENCE.findall(log_text)) / dur), 4)
        return m

    def process(self, inputs: dict) -> dict:
        cfg = self.config
        passed, rejected = [], []
        for item in _vio.as_list(inputs.get("input")):
            s = _to_sample(item)
            if not s.duration_s or not s.width:
                info = _vio.probe(s.path)
                start, end = _vio.span(s)
                s.duration_s = s.duration_s or (round((end - start), 3) if end is not None else info["duration_s"])
                s.fps, s.width, s.height = info["fps"], info["width"], info["height"]
                s.has_audio, s.codec = info["has_audio"], info["codec"]
            reasons: list[str] = []
            if s.duration_s < cfg.min_duration_s:
                reasons.append(f"duration {s.duration_s:.2f}s < {cfg.min_duration_s}s")
            if cfg.max_duration_s and s.duration_s > cfg.max_duration_s:
                reasons.append(f"duration {s.duration_s:.2f}s > {cfg.max_duration_s}s")
            if s.width < cfg.min_width or s.height < cfg.min_height:
                reasons.append(f"resolution {s.width}x{s.height} < {cfg.min_width}x{cfg.min_height}")
            if s.fps < cfg.min_fps:
                reasons.append(f"fps {s.fps} < {cfg.min_fps}")
            if cfg.require_audio and not s.has_audio:
                reasons.append("no audio track")
            measures = self._measure(s) if not reasons else {}
            if measures.get("black_ratio", 0.0) > cfg.max_black_ratio:
                reasons.append(f"black {measures['black_ratio']:.0%} > {cfg.max_black_ratio:.0%}")
            if measures.get("frozen_ratio", 0.0) > cfg.max_frozen_ratio:
                reasons.append(f"frozen {measures['frozen_ratio']:.0%} > {cfg.max_frozen_ratio:.0%}")
            if measures.get("silence_ratio", 0.0) > cfg.max_silence_ratio:
                reasons.append(f"silent {measures['silence_ratio']:.0%} > {cfg.max_silence_ratio:.0%}")
            s.metadata = {**(s.metadata or {}), "quality": {"pass": not reasons, "reasons": reasons, **measures}}
            if reasons and cfg.rejection_policy == "skip":
                rejected.append(s)
            else:
                passed.append(s)
        if cfg.rejection_policy == "fail":
            bad = [x for x in passed if not x.metadata["quality"]["pass"]]
            if bad:
                raise ValueError(
                    "VideoQualityGateNode: %d video(s) failed: %s" % (
                        len(bad), "; ".join(f"{b.path}: {', '.join(b.metadata['quality']['reasons'])}" for b in bad[:5])))
        return {"output": passed, "rejected": rejected}
