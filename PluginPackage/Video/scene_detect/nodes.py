"""SceneDetectNode — shot/scene boundaries with ffmpeg's scene-change score.

Runs ``select='gt(scene,threshold)',showinfo`` over each video (optionally
downscaled for speed) and turns the cut timestamps into scenes. Cuts closer
than ``min_scene_len_s`` are merged. A video with no cut yields one scene
covering it. ``score`` is the ffmpeg scene score (0–1) of the cut that
starts the scene (1.0 for the first scene).
"""
from __future__ import annotations

import importlib
import logging
import re
from typing import Any, ClassVar

from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

_pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
_types = importlib.import_module(f"{_pkg}.types")
_vio = importlib.import_module(f"{_pkg}._vio")
SceneBoundary = _types.SceneBoundary

log = logging.getLogger(__name__)
_PTS = re.compile(r"pts_time:\s*([0-9.]+)")
_SCORE = re.compile(r"lavfi\.scene_score=([0-9.]+)")


def detect_cuts(path: str, threshold: float, start: float = 0.0, end: float | None = None,
                analysis_width: int = 320) -> list[tuple[float, float]]:
    """Return [(time_s, score)] of scene cuts (times relative to ``start``)."""
    args = ["-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-to", f"{end:.3f}"]
    vf = []
    if analysis_width:
        vf.append(f"scale={int(analysis_width)}:-2")
    vf.append(f"select='gt(scene,{float(threshold)})',metadata=print,showinfo")
    args += ["-i", path, "-an", "-vf", ",".join(vf), "-f", "null", "-"]
    text = _vio.run_stderr(args)
    cuts: list[tuple[float, float]] = []
    pending_score = None
    for line in text.splitlines():
        m = _SCORE.search(line)
        if m:
            pending_score = float(m.group(1))
            continue
        if "showinfo" in line:
            t = _PTS.search(line)
            if t:
                cuts.append((float(t.group(1)), float(pending_score or threshold)))
                pending_score = None
    return cuts


class SceneDetectNode(Node):
    """Detect scene cuts with ffmpeg's scene-change score."""

    node_type: ClassVar[str] = "scene_detect"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="scene_detect",
        label="Scene Detect",
        description="Detect shot/scene boundaries with ffmpeg's scene-change score; merges cuts shorter than a minimum scene length.",
        category="Processing",
        version="1.0.0",
        tags=["video", "scene", "shot-boundary", "ffmpeg"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list, cardinality="single", required=True,
                           description="list[VideoSample]"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[SceneBoundary], description="Scenes of every input video"),
    }

    class Config(NodeConfig):
        threshold: float = Field(default=0.3, gt=0, lt=1, title="Threshold",
                                 description="ffmpeg scene-change score (0–1) above which a frame starts a new scene.")
        min_scene_len_s: float = Field(default=1.0, ge=0, title="Min scene length (s)",
                                       description="Cuts closer than this to the previous cut are ignored.")
        analysis_width: int = Field(default=320, ge=0, title="Analysis width (px)",
                                    description="Downscale before scoring for speed (0 = full resolution).")

    def process(self, videos: Any) -> list:
        cfg = self.config
        out: list = []
        for item in _vio.as_list(videos):
            path = _vio.media_path(item)
            start, end = _vio.span(item)
            if end is None:
                end = start + _vio.probe(path)["duration_s"]
            length = end - start
            cuts = detect_cuts(path, cfg.threshold, start, end, cfg.analysis_width)
            bounds: list[tuple[float, float]] = [(0.0, 1.0)]
            for t, score in sorted(cuts):
                if t - bounds[-1][0] >= cfg.min_scene_len_s and length - t >= min(cfg.min_scene_len_s, 0.1):
                    bounds.append((t, score))
            label = str(_vio.get(item, "label", "") or "")
            for i, (t0, score) in enumerate(bounds):
                t1 = bounds[i + 1][0] if i + 1 < len(bounds) else length
                out.append(SceneBoundary(
                    video_path=path, index=i, start_s=round(start + t0, 3), end_s=round(start + t1, 3),
                    score=round(float(score), 4), label=label,
                    metadata={"threshold": cfg.threshold, "n_scenes": len(bounds)},
                ))
        return out
