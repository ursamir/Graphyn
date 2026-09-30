"""VisionHardNegativeMineNode — Hard-negative mining from preds

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any
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
        _types = importlib.import_module("vision_hard_negative_mine.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DetectionResult = _types.DetectionResult
ImageSample = _types.ImageSample
VisionDatasetArtifact = _types.VisionDatasetArtifact

log = logging.getLogger(__name__)


def _num_or(value, default):
    """Config numeric with a real default: only None falls back (0 stays 0)."""
    return default if value is None or value == "" else value

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

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj

def _as_list(obj: Any) -> list:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, tuple):
        return list(obj)
    return [obj]

def _iou(a: list[float], b: list[float]) -> float:
    if len(a) < 4 or len(b) < 4:
        return 0.0
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union else 0.0

def _boxes_of(obj: Any) -> tuple[list, list, list]:
    data = _dump(obj)
    if isinstance(data, dict):
        boxes = list(data.get("boxes") or [])
        scores = list(data.get("scores") or [])
        labels = list(data.get("labels") or [])
        return boxes, scores, labels
    if isinstance(data, list) and data and isinstance(_dump(data[0]), dict):
        boxes, scores, labels = [], [], []
        for item in data:
            d = _dump(item)
            if isinstance(d, dict) and d.get("box"):
                boxes.append(d["box"])
                scores.append(d.get("score") or 0)
                labels.append(d.get("label") or "")
        return boxes, scores, labels
    return [], [], []

def _vision_images(obj: Any) -> list[dict]:
    out = []
    for item in _as_list(obj):
        data = _dump(item)
        if isinstance(data, str):
            data = {"path": data}
        if isinstance(data, dict):
            out.append(data)
    return out

def _hard_neg(config, inputs, types):
    boxes, scores, labels = _boxes_of(inputs.get("predictions"))
    images = _vision_images(inputs.get("dataset"))
    iou_thr = float(_num_or(_cfg(config, "iou_thresh", 0.5), 0.5))
    max_n = int(_cfg(config, "max_negatives", 20) or 20)
    negatives = []
    for im in images:
        gt = im.get("boxes") or []
        for box in boxes:
            if not any(_iou(box, (g.get("box") if isinstance(g, dict) else g) or []) >= iou_thr for g in gt):
                negatives.append(_T(types, "ImageSample", path=str(im.get("path") or ""), boxes=[{"box": box, "hard_negative": True}], metadata={"score": scores[boxes.index(box)] if box in boxes and boxes.index(box) < len(scores) else 0}))
            if len(negatives) >= max_n:
                return negatives
    return negatives



class VisionHardNegativeMineNode(Node):
    """Hard-negative mining from preds"""

    node_type: ClassVar[str] = "vision_hard_negative_mine"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="vision_hard_negative_mine",
        label="Vision Hard Negative Mine",
        description="Hard-negative mining from preds",
        category="ML",
        version="0.1.0",
        tags=["vision"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "predictions": InputPort(name="predictions", data_type=object, required=True, description="list[DetectionResult] NEW"),
        "dataset": InputPort(name="dataset", data_type=object, required=True, description="VisionDatasetArtifact NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[ImageSample] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        iou_thresh: float = Field(default=0.5, title="Iou thresh", description="Iou thresh.")
        max_negatives: int = Field(default=500, title="Max negatives", description="Max negatives.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'vision_hard_negative_mine'
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
            raise ImportError(f"vision_hard_negative_mine: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _hard_neg(self.config, inputs, _types)}
