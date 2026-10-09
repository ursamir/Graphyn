"""VideoExporterNode — write a video dataset folder with a manifest.

Copies (or hard-links) each video/clip into
``{output_dir}/{label or 'unlabeled'}/`` — virtual segments are cut to
their own MP4 — and writes ``manifest.jsonl`` + ``manifest.csv``. Records
on the optional ``annotations`` input (captions, action predictions,
alignment records, embeddings, …) are attached to the clip they belong to:
same file, or same source video with a timestamp inside the clip's span.
The folder is published as a file tree.
"""
from __future__ import annotations

import csv
import importlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np
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


def _plain(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, np.ndarray):
                out[k] = {"shape": list(v.shape), "dtype": str(v.dtype)} if v.size > 64 else v.tolist()
            else:
                out[k] = _plain(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


class VideoExporterNode(Node):
    """Export videos/clips into a labelled folder with JSONL/CSV manifests."""

    node_type: ClassVar[str] = "video_exporter"
    _siso: ClassVar[bool] = False

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="video_exporter",
        label="Video Exporter",
        description="Write videos/clips into a label-per-folder dataset with manifest.jsonl/manifest.csv, attaching captions, predictions and other per-clip records.",
        category="Output",
        version="1.0.0",
        tags=["video", "export", "dataset", "manifest"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list, cardinality="single", required=True,
                           description="list[VideoSample] (videos or clips)"),
        "annotations": InputPort(name="annotations", data_type=list | None, cardinality="single", required=False,
                                 description="Per-clip records: CaptionRecord, PredictionResult, AvAlignedSample, …"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[VideoSample], description="Exported videos (new paths)"),
        "manifest": OutputPort(name="manifest", data_type=str, description="Path of manifest.jsonl"),
    }

    class Config(NodeConfig):
        output_dir: str = Field(default="workspace/datasets/output/video", title="Output dir")
        link_mode: Literal["copy", "hardlink"] = Field(default="copy", title="Link mode",
                                                        description="hardlink saves space when on the same filesystem (falls back to copy).")
        clean: bool = Field(default=False, title="Clean output dir first")

    @staticmethod
    def _belongs(ann: Any, clip_path: str, source: str, a: float, b: float) -> bool:
        """Same clip file, or same source video with a source timestamp inside [a, b)."""
        meta = _vio.get(ann, "metadata", {}) or {}
        named = _vio.get(ann, "video_path") or meta.get("video_path")
        if named:
            if str(named) == clip_path:
                return True
            if str(named) != source:
                return False  # belongs to another clip file
        src = _vio.get(ann, "source_path") or named
        if not src or str(src) != source:
            return False
        t = _vio.get(ann, "timestamp_s")
        if t is None and named and str(named) == source:
            t = meta.get("start_s")  # segment records expressed on the source timeline
        return t is not None and a - 1e-3 <= float(t) < b + 1e-3

    def process(self, inputs: dict) -> dict:
        cfg = self.config
        root = Path(cfg.output_dir)
        if cfg.clean and root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        anns = _vio.as_list(inputs.get("annotations"))
        exported: list = []
        rows: list[dict] = []
        files: list[str] = []
        for i, item in enumerate(_vio.as_list(inputs.get("input"))):
            path = _vio.media_path(item)
            start, end = _vio.span(item)
            label = str(_vio.get(item, "label", "") or "") or "unlabeled"
            source = str(_vio.get(item, "source_path", "") or path)
            meta = dict(_vio.get(item, "metadata", {}) or {})
            s0 = float(meta.get("source_start_s", start))
            s1 = float(meta.get("source_end_s", end if end is not None else 1e12))
            dest_dir = root / label
            dest_dir.mkdir(parents=True, exist_ok=True)
            virtual = start > 0 or (end is not None and abs(end - _vio.probe(path)["duration_s"]) > 0.05)
            if virtual:
                dest = dest_dir / f"{Path(path).stem}_{int(start * 1000):08d}.mp4"
                args = ["-v", "error", "-y", "-ss", f"{start:.3f}"] + (["-to", f"{end:.3f}"] if end is not None else [])
                _vio.run(args + ["-i", path, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(dest)])
            else:
                dest = dest_dir / Path(path).name
                if dest.exists():
                    dest.unlink()
                if cfg.link_mode == "hardlink":
                    try:
                        os.link(path, dest)
                    except OSError:
                        shutil.copy2(path, dest)
                else:
                    shutil.copy2(path, dest)
            info = _vio.probe(dest)
            mine = [_plain(a) for a in anns if self._belongs(a, path, source, s0, s1)]
            rel = str(dest.relative_to(root))
            files.append(rel)
            row = {"file": rel, "label": label, "source_path": source, "source_start_s": round(s0, 3),
                   "source_end_s": round(s1, 3) if s1 < 1e11 else None, "duration_s": info["duration_s"],
                   "fps": info["fps"], "width": info["width"], "height": info["height"],
                   "has_audio": info["has_audio"], "annotations": mine}
            rows.append(row)
            exported.append(VideoSample(path=str(dest), label=label, duration_s=info["duration_s"], fps=info["fps"],
                                        width=info["width"], height=info["height"], n_frames=info["n_frames"],
                                        has_audio=info["has_audio"], codec=info["codec"], size_bytes=info["size_bytes"],
                                        source_path=source, metadata={**meta, "n_annotations": len(mine)}))
        if not rows:
            raise ValueError("VideoExporterNode: nothing to export (empty input)")
        manifest = root / "manifest.jsonl"
        with manifest.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, default=str) + "\n")
        with (root / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "label", "source_path", "source_start_s", "source_end_s", "duration_s", "n_annotations", "first_annotation"])
            for r in rows:
                first = r["annotations"][0] if r["annotations"] else {}
                text = first.get("text") or first.get("predicted_label") or ""
                w.writerow([r["file"], r["label"], r["source_path"], r["source_start_s"], r["source_end_s"],
                            r["duration_s"], len(r["annotations"]), text])
        files += ["manifest.jsonl", "manifest.csv"]
        self.publish_files(root, files, total=len(files))
        return {"output": exported, "manifest": str(manifest)}
