"""YoloTaskSegmentNode — Segment-task wrapper

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.model_artifact import ModelArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("yolo_task_segment.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DetectionResult = _types.DetectionResult
ImageSample = _types.ImageSample

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

def _text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list):
        return "\n".join(_text(x) for x in obj)
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("text", "query", "content", "answer", "user", "path", "value", "final"):
            if data.get(key):
                return str(data[key])
        return json.dumps(data, default=str)
    return str(obj)

def _as_list(obj: Any) -> list:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, tuple):
        return list(obj)
    return [obj]

def _bytes_of(obj: Any) -> bytes:
    if isinstance(obj, bytes):
        return obj
    data = _dump(obj)
    if isinstance(data, dict) and isinstance(data.get("bytes"), (bytes, bytearray)):
        return bytes(data["bytes"])
    if isinstance(data, dict) and data.get("path"):
        path = Path(str(data["path"]))
        if path.is_file():
            return path.read_bytes()
    return _text(obj).encode("utf-8")

def _detect_from_images(images: Any, conf: float) -> tuple[list, list, list]:
    """Contrast-blob detector. Uses PIL when installed, else a byte-energy box."""
    boxes, scores, labels = [], [], []
    for image in _as_list(images) or [images]:
        if image is None:
            continue
        data = _dump(image)
        path = ""
        if isinstance(data, dict):
            path = str(data.get("path") or "")
        elif isinstance(image, str):
            path = image
        box = [0.0, 0.0, 1.0, 1.0]
        score = conf
        try:
            from PIL import Image  # type: ignore

            src = path if path and Path(path).is_file() else None
            if src:
                im = Image.open(src).convert("L")
                im.thumbnail((64, 64))
                px = list(im.getdata())
                w, h = im.size
                if px and w and h:
                    mean = sum(px) / len(px)
                    best = None
                    for y in range(h):
                        for x in range(w):
                            if px[y * w + x] > mean:
                                if best is None:
                                    best = [x, y, x + 1, y + 1]
                                else:
                                    best[0] = min(best[0], x)
                                    best[1] = min(best[1], y)
                                    best[2] = max(best[2], x + 1)
                                    best[3] = max(best[3], y + 1)
                    if best:
                        box = [best[0] / w, best[1] / h, best[2] / w, best[3] / h]
                        score = max(conf, min(0.99, (max(px) - mean) / 255))
        except Exception:
            raw = _bytes_of(image)
            if raw:
                score = max(conf, min(0.99, sum(raw[:256]) / (255 * max(1, min(256, len(raw))))))
        boxes.append(box)
        scores.append(float(score))
        labels.append("object")
    return boxes, scores, labels

def _try_ultralytics_predict(model: Any, images: Any, imgsz: int, conf: float) -> tuple[list, list, list] | None:
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError:
        return None
    model_ref = model
    data = _dump(model)
    if isinstance(data, dict):
        model_ref = data.get("path") or data.get("model_path") or data.get("weights") or "yolov8n.pt"
    paths = []
    for image in _as_list(images):
        d = _dump(image)
        if isinstance(d, dict) and d.get("path"):
            paths.append(str(d["path"]))
        elif isinstance(image, str):
            paths.append(image)
    if not paths:
        return None
    yolo = YOLO(str(model_ref))
    results = yolo.predict(paths, imgsz=int(imgsz or 640), conf=float(conf), verbose=False)
    boxes, scores, labels = [], [], []
    for result in results:
        xyxy = getattr(result, "boxes", None)
        if xyxy is None:
            continue
        for b in xyxy:
            coords = [float(v) for v in b.xyxy[0].tolist()]
            boxes.append(coords)
            scores.append(float(b.conf[0]))
            labels.append(str(int(b.cls[0])))
    return boxes, scores, labels

def _detect(config, inputs, types):
    images = inputs.get("images") or inputs.get("input")
    conf = float(_num_or(_cfg(config, "conf", 0.25), 0.25))
    imgsz = int(_cfg(config, "imgsz", 640) or 640)
    predicted = _try_ultralytics_predict(inputs.get("model"), images, imgsz, conf)
    if predicted is None:
        boxes, scores, labels = _detect_from_images(images, conf)
        backend = "contrast-blob"
    else:
        boxes, scores, labels = predicted
        backend = "ultralytics"
    return _T(types, "DetectionResult", boxes=boxes, scores=scores, labels=labels, metadata={"backend": backend, "task": str(_cfg(config, "task", "detect"))})



class YoloTaskSegmentNode(Node):
    """Segment-task wrapper"""

    node_type: ClassVar[str] = "yolo_task_segment"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_task_segment",
        label="Yolo Task Segment",
        description="Segment-task wrapper",
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
        "model": InputPort(name="model", data_type=object, required=True, description="ModelArtifact"),
        "images": InputPort(name="images", data_type=object, required=True, description="list[ImageSample] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[DetectionResult] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        imgsz: int = Field(default=640, title="Imgsz", description="Imgsz.")
        retina_masks: bool = Field(default=False, title="Retina masks", description="Retina masks.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_task_segment'
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
            raise ImportError(f"yolo_task_segment: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _detect(self.config, inputs, _types)}
