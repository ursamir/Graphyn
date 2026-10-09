"""ClipSegmentNode — cut videos into clips by scene or fixed window.

mode=scenes uses the ``scenes`` input (from scene_detect); mode=fixed cuts
``window_s`` windows every ``hop_s``. With ``write_files`` each clip is
encoded to ``{output_dir}/{stem}_c{NNN}.mp4`` (H.264/AAC, frame-accurate
cuts) and published as a file tree; otherwise clips are virtual segments
(``start_s``/``end_s`` into the source file) and nothing is written.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
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


class ClipSegmentNode(Node):
    """Cut videos into clips (scene-based or fixed windows)."""

    node_type: ClassVar[str] = "clip_segment"
    _siso: ClassVar[bool] = False

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="clip_segment",
        label="Clip Segment",
        description="Cut videos into clips at detected scenes or fixed windows; writes H.264 clips with ffmpeg (or emits virtual segments).",
        category="Processing",
        version="1.0.0",
        tags=["video", "clips", "segmentation", "ffmpeg"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "video": InputPort(name="video", data_type=list, cardinality="single", required=True,
                           description="list[VideoSample]"),
        "scenes": InputPort(name="scenes", data_type=list | None, cardinality="single", required=False,
                            description="list[SceneBoundary] from scene_detect (mode=scenes)"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[VideoSample], description="One VideoSample per clip"),
    }

    class Config(NodeConfig):
        mode: Literal["scenes", "fixed"] = Field(default="scenes", title="Mode",
                                                 description="scenes = cut at scene boundaries (needs the scenes input); fixed = fixed windows.")
        window_s: float = Field(default=10.0, gt=0, title="Window (s)", description="Clip length for mode=fixed.")
        hop_s: float = Field(default=0.0, ge=0, title="Hop (s)", description="Step between fixed windows (0 = window_s, no overlap).")
        min_clip_s: float = Field(default=0.5, ge=0, title="Min clip (s)", description="Drop clips shorter than this.")
        max_clip_s: float = Field(default=0.0, ge=0, title="Max clip (s)", description="Split longer scenes into pieces of at most this (0 = no limit).")
        max_clips: int = Field(default=0, ge=0, title="Max clips per video", description="0 = no limit.")
        write_files: bool = Field(default=True, title="Write clip files", description="Encode each clip to its own MP4; off = virtual segments.")
        output_dir: str = Field(default="workspace/datasets/video/clips", title="Output dir")
        crf: int = Field(default=23, ge=0, le=51, title="H.264 CRF", description="Quality for written clips (lower = better).")

    def _spans(self, video: Any, scenes: list) -> list[tuple[float, float, dict]]:
        cfg = self.config
        path = _vio.media_path(video)
        start, end = _vio.span(video)
        if end is None:
            end = start + _vio.probe(path)["duration_s"]
        spans: list[tuple[float, float, dict]] = []
        if cfg.mode == "scenes":
            mine = [s for s in scenes if str(_vio.get(s, "video_path", "")) == path]
            if not mine:
                raise ValueError(
                    f"ClipSegmentNode: mode=scenes but no scenes for {path}; connect scene_detect → scenes or use mode=fixed")
            for s in sorted(mine, key=lambda x: float(_vio.get(x, "start_s", 0.0))):
                a = max(start, float(_vio.get(s, "start_s", 0.0)))
                b = min(end, float(_vio.get(s, "end_s", end)))
                meta = {"scene_index": int(_vio.get(s, "index", 0)), "scene_score": float(_vio.get(s, "score", 0.0))}
                if cfg.max_clip_s and b - a > cfg.max_clip_s:
                    t = a
                    while t < b - 1e-6:
                        spans.append((t, min(b, t + cfg.max_clip_s), dict(meta)))
                        t += cfg.max_clip_s
                else:
                    spans.append((a, b, meta))
        else:
            hop = cfg.hop_s or cfg.window_s
            t = start
            while t < end - 1e-6:
                spans.append((t, min(end, t + cfg.window_s), {}))
                t += hop
        spans = [s for s in spans if s[1] - s[0] >= cfg.min_clip_s]
        if cfg.max_clips:
            spans = spans[: cfg.max_clips]
        return spans

    def process(self, inputs: dict) -> dict:
        cfg = self.config
        videos = _vio.as_list(inputs.get("video"))
        scenes = _vio.as_list(inputs.get("scenes"))
        out_dir = Path(cfg.output_dir)
        written: list[str] = []
        clips: list = []
        for video in videos:
            path = _vio.media_path(video)
            info = _vio.probe(path)
            label = str(_vio.get(video, "label", "") or "")
            stem = Path(path).stem
            for i, (a, b, meta) in enumerate(self._spans(video, scenes)):
                common = dict(label=label, duration_s=round(b - a, 3), fps=info["fps"], width=info["width"],
                              height=info["height"], n_frames=int(round((b - a) * info["fps"])),
                              has_audio=info["has_audio"], codec="h264" if cfg.write_files else info["codec"],
                              source_path=path,
                              metadata={**meta, "clip_index": i, "source_start_s": round(a, 3), "source_end_s": round(b, 3)})
                if cfg.write_files:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    dest = out_dir / f"{stem}_c{i:03d}.mp4"
                    args = ["-v", "error", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", path,
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg.crf), "-pix_fmt", "yuv420p"]
                    args += ["-c:a", "aac", "-b:a", "128k"] if info["has_audio"] else ["-an"]
                    args += ["-movflags", "+faststart", str(dest)]
                    _vio.run(args)
                    written.append(dest.name)
                    clips.append(VideoSample(path=str(dest), start_s=0.0, end_s=None,
                                             size_bytes=dest.stat().st_size, **common))
                else:
                    clips.append(VideoSample(path=path, start_s=round(a, 3), end_s=round(b, 3), **common))
        if written:
            self.publish_files(out_dir, written, total=len(written))
        return {"output": clips}
