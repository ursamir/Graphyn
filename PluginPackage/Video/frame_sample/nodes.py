"""FrameSampleNode — extract frames from videos/clips as JPEG images.

Modes: ``fps`` (N frames per second), ``every_n`` (every N-th decoded
frame), ``keyframes`` (I-frames only) and ``uniform`` (``num_frames``
evenly spaced over each video). Timestamps come from ffmpeg's ``showinfo``
(exact pts) and are reported relative to the original source video.
Frames are written to ``{output_dir}/{video-stem}/f_NNNNN.jpg`` and
published as a file tree.
"""
from __future__ import annotations

import importlib
import logging
import re
import shutil
import tempfile
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
ImageSample = _types.ImageSample

log = logging.getLogger(__name__)
_PTS = re.compile(r"pts_time:\s*([0-9.]+)")
_SIZE = re.compile(r"\bs:(\d+)x(\d+)")


class FrameSampleNode(Node):
    """Extract frames (fps / every-n / keyframes / uniform) to JPEG files."""

    node_type: ClassVar[str] = "frame_sample"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="frame_sample",
        label="Frame Sample",
        description="Extract frames from videos or clips (fps, every N-th, keyframes, or uniform N) as JPEGs with exact timestamps.",
        category="Processing",
        version="1.0.0",
        tags=["video", "frames", "sampling", "ffmpeg"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list, cardinality="single", required=True,
                           description="list[VideoSample] (videos or clips)"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[ImageSample], description="Extracted frames"),
    }

    class Config(NodeConfig):
        mode: Literal["fps", "every_n", "keyframes", "uniform"] = Field(default="fps", title="Mode")
        fps: float = Field(default=1.0, gt=0, title="Frames per second", description="mode=fps")
        every_n: int = Field(default=30, ge=1, title="Every N-th frame", description="mode=every_n")
        num_frames: int = Field(default=8, ge=1, title="Frames per video", description="mode=uniform")
        max_frames: int = Field(default=200, ge=0, title="Max frames per video", description="0 = no limit.")
        width: int = Field(default=0, ge=0, title="Resize width (px)", description="0 = keep size; height keeps aspect.")
        jpeg_quality: int = Field(default=3, ge=2, le=31, title="JPEG quality (2 best – 31 worst)")
        output_dir: str = Field(default="workspace/datasets/video/frames", title="Output dir")

    def _extract(self, path: str, start: float, end: float | None, dest: Path) -> list[tuple[Path, float, int, int]]:
        cfg = self.config
        dest.mkdir(parents=True, exist_ok=True)
        for old in dest.glob("f_*.jpg"):  # re-runs must not mix in stale frames
            old.unlink()
        scale = [f"scale={cfg.width}:-2"] if cfg.width else []
        if cfg.mode == "uniform":
            if end is None:
                end = start + _vio.probe(path)["duration_s"]
            res = []
            for k, t in enumerate(_vio.uniform_times(end - start, cfg.num_frames, start)):
                f = dest / f"f_{k:05d}.jpg"
                _vio.run(["-v", "error", "-y", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                          *(["-vf", scale[0]] if scale else []), "-q:v", str(cfg.jpeg_quality), str(f)])
                if f.exists():
                    res.append((f, t, 0, 0))
            return res
        if cfg.mode == "fps":
            sel = [f"fps={cfg.fps}"]
        elif cfg.mode == "every_n":
            sel = [f"select='not(mod(n\\,{cfg.every_n}))'"]
        else:
            sel = ["select='eq(pict_type\\,I)'"]
        tmp = Path(tempfile.mkdtemp(prefix="fs_", dir=str(dest)))
        try:
            args = ["-ss", f"{start:.3f}"]
            if end is not None:
                args += ["-to", f"{end:.3f}"]
            args += ["-i", path, "-an", "-vf", ",".join(sel + scale + ["showinfo"]), "-fps_mode", "vfr"]
            if cfg.max_frames:
                args += ["-frames:v", str(cfg.max_frames)]
            args += ["-q:v", str(cfg.jpeg_quality), str(tmp / "%05d.jpg")]
            log_text = _vio.run_stderr(args)
            infos = [( float(m.group(1)), line) for line in log_text.splitlines() if "showinfo" in line
                     for m in [_PTS.search(line)] if m]
            files = sorted(tmp.glob("*.jpg"))
            res = []
            for k, f in enumerate(files):
                t_rel, line = infos[k] if k < len(infos) else (k / cfg.fps if cfg.mode == "fps" else 0.0, "")
                sz = _SIZE.search(line)
                final = dest / f"f_{k:05d}.jpg"
                f.replace(final)
                res.append((final, start + t_rel, int(sz.group(1)) if sz else 0, int(sz.group(2)) if sz else 0))
            return res
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def process(self, videos: Any) -> list:
        cfg = self.config
        root = Path(cfg.output_dir)
        frames: list = []
        written: list[str] = []
        for item in _vio.as_list(videos):
            path = _vio.media_path(item)
            start, end = _vio.span(item)
            stem = Path(path).stem + (f"_{int(round(start * 1000))}ms" if start > 0 else "")
            source = str(_vio.get(item, "source_path", "") or path)
            offset = float((_vio.get(item, "metadata", {}) or {}).get("source_start_s", 0.0)) if source != path else 0.0
            label = str(_vio.get(item, "label", "") or "")
            got = self._extract(path, start, end, root / stem)
            if not got:
                raise ValueError(f"FrameSampleNode: no frames extracted from {path} (mode={cfg.mode})")
            for k, (f, t, w, h) in enumerate(got):
                if not w:
                    info = _vio.probe(str(f))
                    w, h = info["width"], info["height"]
                frames.append(ImageSample(
                    path=str(f), source_path=source, timestamp_s=round(offset + t, 3), index=k,
                    width=w, height=h, label=label,
                    metadata={"video_path": path, "clip_time_s": round(t, 3), "mode": cfg.mode},
                ))
                written.append(str(f.relative_to(root)))
        if written:
            self.publish_files(root, written, total=len(written))
        return frames
