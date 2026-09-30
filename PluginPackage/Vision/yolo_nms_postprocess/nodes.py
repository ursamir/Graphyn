"""YoloNmsPostprocessNode — Standalone NMS postprocess

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
        _types = importlib.import_module("yolo_nms_postprocess.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DetectionResult = _types.DetectionResult

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

def _nms(boxes: list, scores: list, iou_thr: float, max_det: int) -> tuple[list, list, list]:
    order = sorted(range(len(boxes)), key=lambda i: float(scores[i] if i < len(scores) else 0), reverse=True)
    keep: list[int] = []
    for i in order:
        if all(_iou(boxes[i], boxes[j]) <= iou_thr for j in keep):
            keep.append(i)
        if len(keep) >= max_det:
            break
    return keep

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

def _nms_node(config, inputs, types):
    boxes, scores, labels = _boxes_of(inputs.get("input") or inputs.get("predictions"))
    iou = float(_num_or(_cfg(config, "iou", 0.5), 0.5))
    conf = float(_num_or(_cfg(config, "conf", 0.25), 0))
    max_det = int(_cfg(config, "max_det", 100) or 100)
    keep_idx = [i for i in range(len(scores)) if float(scores[i]) >= conf]
    boxes = [boxes[i] for i in keep_idx if i < len(boxes)]
    scores = [scores[i] for i in keep_idx]
    labels = [labels[i] for i in keep_idx] if labels else [""] * len(boxes)
    kept = _nms(boxes, scores, iou, max_det)
    return _T(types, "DetectionResult", boxes=[boxes[i] for i in kept], scores=[scores[i] for i in kept], labels=[labels[i] if i < len(labels) else "" for i in kept], metadata={"nms": True})



class YoloNmsPostprocessNode(Node):
    """Standalone NMS postprocess"""

    node_type: ClassVar[str] = "yolo_nms_postprocess"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_nms_postprocess",
        label="Yolo Nms Postprocess",
        description="Standalone NMS postprocess",
        category="Processing",
        version="0.1.0",
        tags=["vision"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[DetectionResult] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[DetectionResult] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        iou: float = Field(default=0.45, title="Iou", description="Iou.")
        conf: float = Field(default=0.25, title="Conf", description="Conf.")
        max_det: int = Field(default=300, title="Max det", description="Max det.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_nms_postprocess'
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
            raise ImportError(f"yolo_nms_postprocess: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _nms_node(self.config, inputs, _types)}
