"""YoloTrackNode — ByteTrack-style multi-object track

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
        _types = importlib.import_module("yolo_track.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DetectionResult = _types.DetectionResult
TrackResult = _types.TrackResult

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

def _track(config, inputs, types):
    boxes, scores, labels = _boxes_of(inputs.get("detections"))
    tracks = []
    next_id = 1
    active: list[dict] = []
    frames = boxes if boxes and isinstance(boxes[0], list) and boxes and isinstance(boxes[0][0], list) else [boxes]
    # Single-frame list of boxes.
    if boxes and isinstance(boxes[0], (int, float)):
        frames = [boxes]
    elif boxes and isinstance(boxes[0], list) and boxes[0] and isinstance(boxes[0][0], (int, float)):
        frames = [boxes]
    for frame in frames:
        frame_boxes = frame if frame and isinstance(frame[0], list) else [frame]
        for box in frame_boxes:
            matched = None
            for tr in active:
                if _iou(tr["box"], box) >= float(_num_or(_cfg(config, "track_high_thresh", 0.5), 0.5)):
                    matched = tr
                    break
            if matched is None:
                matched = {"id": next_id, "box": box}
                next_id += 1
                active.append(matched)
            else:
                matched["box"] = box
            tracks.append({"id": matched["id"], "box": box})
    return _T(types, "TrackResult", tracks=tracks, metadata={"tracker": str(_cfg(config, "tracker", "iou"))})



class YoloTrackNode(Node):
    """ByteTrack-style multi-object track"""

    node_type: ClassVar[str] = "yolo_track"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_track",
        label="Yolo Track",
        description="ByteTrack-style multi-object track",
        category="Inference",
        version="0.1.0",
        tags=["vision"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "detections": InputPort(name="detections", data_type=object, required=True, description="list[DetectionResult] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[TrackResult] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        tracker: str = Field(default='bytetrack', title="Tracker", description="Tracker.")
        track_high_thresh: float = Field(default=0.5, title="Track high thresh", description="Track high thresh.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_track'
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
            raise ImportError(f"yolo_track: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _track(self.config, inputs, _types)}
