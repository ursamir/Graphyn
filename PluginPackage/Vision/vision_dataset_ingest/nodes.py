"""VisionDatasetIngestNode — COCO/YOLO/folder image ingest

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("vision_dataset_ingest.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ImageSample = _types.ImageSample

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _T(types: Any, name: str, **kwargs: Any) -> Any:
    cls = getattr(types, name, None) if types is not None else None
    if cls is None:
        return kwargs
    fields = getattr(cls, "model_fields", None)
    if isinstance(fields, dict) and fields:
        kwargs = {k: v for k, v in kwargs.items() if k in fields}
    return cls(**kwargs)

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _yolo_label_path(img: Path) -> Path:
    parts = list(img.parts)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "labels"
            return Path(*parts).with_suffix(".txt")
    return img.with_suffix(".txt")


def _yolo_ingest(root: Path, paths: list, split: str, types):
    """YOLO layout: images/**/x.jpg with labels/**/x.txt rows 'cls cx cy w h' (normalised)."""
    out = []
    for img in paths:
        if img.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        lp = _yolo_label_path(img)
        boxes = []
        if lp.is_file():
            for ln, line in enumerate(lp.read_text(encoding="utf-8").splitlines(), 1):
                vals = line.split()
                if not vals:
                    continue
                if len(vals) < 5:
                    raise ValueError(f"vision_dataset_ingest: malformed YOLO label {lp}:{ln}: {line!r}")
                boxes.append({"class_id": int(float(vals[0])), "xywhn": [float(v) for v in vals[1:5]]})
        label = str(boxes[0]["class_id"]) if boxes else None
        out.append(_T(types, "ImageSample", path=str(img), label=label, boxes=boxes,
                      metadata={"split": split, "label_path": str(lp) if lp.is_file() else ""}))
    return out


def _vision_ingest(config, inputs, types):
    root = Path(str(_cfg(config, "path", "") or ""))
    split = str(_cfg(config, "split", "train") or "train")
    images = []
    paths = [root] if root.is_file() else sorted(root.rglob("*")) if root.is_dir() else []
    source_type = str(_cfg(config, "source_type", "folder") or "folder")
    if source_type == "yolo":
        return _yolo_ingest(root, paths, split, types)
    if source_type != "folder":
        raise ValueError(f"vision_dataset_ingest: unsupported source_type {source_type!r} (folder|yolo)")
    for path in paths:
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".txt", ".json"}:
            continue
        images.append(_T(types, "ImageSample", path=str(path), label=path.parent.name, metadata={"split": split}))
    return images



class VisionDatasetIngestNode(Node):
    """COCO/YOLO/folder image ingest"""

    node_type: ClassVar[str] = "vision_dataset_ingest"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="vision_dataset_ingest",
        label="Vision Dataset Ingest",
        description="COCO/YOLO/folder image ingest",
        category="Input",
        version="0.1.0",
        tags=["vision"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {}

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[ImageSample] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        source_type: Literal["folder", "yolo"] = Field(default="folder", title="Source type", description="folder: every image/label file (label = parent dir); yolo: images/ + labels/*.txt boxes.")
        path: str = Field(default='', title="Path", description="Path.")
        split: str = Field(default='train', title="Split", description="Split.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'vision_dataset_ingest'
        if stub:
            log.warning(
                "%s: stub mode (config.stub=True) returned a placeholder, not a real result",
                getattr(self, "node_type", type(self).__name__),
            )
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            _out = out_dir / 'stub'
            result = []
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"vision_dataset_ingest: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _vision_ingest(self.config, inputs, _types)}
