"""VideoIngestNode — find video files and probe them with ffprobe.

Walks ``path`` (a file or folder), keeps files with the configured
extensions, and emits one VideoSample per file with duration, fps,
resolution, codec and audio facts. ``label_from_parent`` uses the parent
folder name as the label (class-per-folder datasets). Unreadable files are
either skipped (recorded in metadata of the run log) or raise, per
``on_error``.
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
from app.core.nodes.ports import OutputPort

_pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
_types = importlib.import_module(f"{_pkg}.types")
_vio = importlib.import_module(f"{_pkg}._vio")
VideoSample = _types.VideoSample

log = logging.getLogger(__name__)


class VideoIngestNode(Node):
    """Ingest video files/folders (ffprobe metadata, no decoding)."""

    node_type: ClassVar[str] = "video_ingest"
    _siso: ClassVar[bool] = False

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="video_ingest",
        label="Video Ingest",
        description="Find video files in a folder (or one file) and probe duration, fps, resolution, codec and audio with ffprobe.",
        category="Input",
        version="1.0.0",
        tags=["video", "ingest", "ffprobe"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict] = {}
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[VideoSample], description="One VideoSample per video file"),
    }

    class Config(NodeConfig):
        path: str = Field(default="", title="Path", description="Video file or folder (workspace-relative or absolute).")
        recursive: bool = Field(default=True, title="Recursive", description="Walk sub-folders.")
        extensions: list[str] = Field(
            default_factory=lambda: [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ogv"],
            title="Extensions", description="File extensions to keep (with or without the dot).")
        label_from_parent: bool = Field(default=False, title="Label from parent folder",
                                        description="Use the parent folder name as each video's label.")
        max_files: int = Field(default=0, ge=0, title="Max files", description="Stop after this many files (0 = all).")
        on_error: Literal["skip", "raise"] = Field(default="skip", title="On unreadable file",
                                                   description="skip = log and continue; raise = fail the node.")

    def _files(self) -> list[Path]:
        raw = (self.config.path or "").strip()
        if not raw:
            raise ValueError("VideoIngestNode: config.path is required (a video file or folder)")
        root = Path(raw).expanduser()
        if not root.exists():
            raise FileNotFoundError(f"VideoIngestNode: path not found: {raw}")
        exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in (self.config.extensions or [])}
        if root.is_file():
            return [root]
        walker = root.rglob("*") if self.config.recursive else root.glob("*")
        files = sorted(p for p in walker if p.is_file() and (not exts or p.suffix.lower() in exts))
        if self.config.max_files:
            files = files[: self.config.max_files]
        return files

    def process(self, inputs: dict | None = None) -> dict:
        out = []
        skipped = []
        for fp in self._files():
            try:
                info = _vio.probe(fp)
            except Exception as exc:
                if self.config.on_error == "raise":
                    raise
                log.warning("VideoIngestNode: skipping %s (%s)", fp, exc)
                skipped.append(str(fp))
                continue
            out.append(VideoSample(
                path=str(fp),
                label=fp.parent.name if self.config.label_from_parent else "",
                start_s=0.0,
                end_s=None,
                duration_s=info["duration_s"],
                fps=info["fps"],
                width=info["width"],
                height=info["height"],
                n_frames=info["n_frames"],
                has_audio=info["has_audio"],
                codec=info["codec"],
                size_bytes=info["size_bytes"],
                source_path=str(fp),
                metadata={"container": info["container"], "audio_codec": info["audio_codec"],
                          "audio_sample_rate": info["audio_sample_rate"]},
            ))
        if not out:
            raise ValueError(
                f"VideoIngestNode: no readable videos under {self.config.path!r}"
                + (f" ({len(skipped)} unreadable)" if skipped else ""))
        return {"output": out}
