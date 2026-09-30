"""YoloPredictNode — YOLO predict images/video

Default config.stub=False runs detection.
When stub=False, runs ultralytics YOLO.predict.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.model_artifact import ModelArtifact


def _force_cpu() -> None:
    """Stay on CPU when another process owns the GPU. Default on."""
    import os

    flag = os.environ.get("GRAPHYN_ML_FORCE_CPU", "1").strip().lower()
    if flag in ("0", "false", "no"):
        return
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    os.environ.setdefault("ULTRALYTICS_OFFLINE", "1")

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("yolo_predict.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DetectionResult = _types.DetectionResult
ImageSample = _types.ImageSample

log = logging.getLogger(__name__)


def _num_or(value, default):
    """Config numeric with a real default: only None falls back (0 stays 0)."""
    return default if value is None or value == "" else value


def _image_sources(raw: Any) -> list[str]:
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            out.append(item)
        elif hasattr(item, "path") and getattr(item, "path"):
            out.append(str(item.path))
        elif isinstance(item, dict) and item.get("path"):
            out.append(str(item["path"]))
    return out


class YoloPredictNode(Node):
    """YOLO predict images/video"""

    node_type: ClassVar[str] = "yolo_predict"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_predict",
        label="Yolo Predict",
        description="YOLO predict images/video",
        category="Inference",
        version="0.2.0",
        tags=["vision"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "model": InputPort(name="model", data_type=object, required=True, description="ModelArtifact"),
        "images": InputPort(name="images", data_type=object, required=True, description="list[ImageSample] NEW|list[str]"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[DetectionResult] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        task: str = Field(default="detect", title="Task", description="Task.")
        imgsz: int = Field(default=640, title="Imgsz", description="Imgsz.")
        conf: float = Field(default=0.25, title="Conf", description="Conf.")
        iou: float = Field(default=0.7, title="Iou", description="Iou.")
        max_det: int = Field(default=300, title="Max det", description="Max det.")
        device: Literal["cpu", "auto", "cuda", "mps"] = Field(default="cpu", title="Device", description="Prefer cpu when GPU is contested; auto lets ultralytics pick.")

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path("workspace/artifacts") / "vision" / "yolo_predict"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if stub:
            return {"output": []}
        return self._process_real(inputs, out_dir)

    def _process_real(self, inputs: dict, out_dir: Path):
        try:
            _force_cpu()
            from ultralytics import YOLO  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "ultralytics is not installed in this plugin venv. "
                "Use Plugins → Install optional (venv)."
            ) from exc

        model_in = inputs.get("model") or inputs.get("input")
        weights = None
        if isinstance(model_in, ModelArtifact) or hasattr(model_in, "model_path"):
            weights = getattr(model_in, "model_path", None)
        elif isinstance(model_in, str):
            weights = model_in
        elif isinstance(model_in, dict):
            weights = model_in.get("model_path") or model_in.get("path")
        if not weights:
            weights = "yolov8n.pt"

        sources = _image_sources(inputs.get("images"))
        if not sources:
            raise RuntimeError("yolo_predict: images paths required when stub=False")

        device = str(getattr(self.config, "device", "cpu") or "cpu")
        model = YOLO(str(weights))
        results = model.predict(
            source=sources,
            imgsz=int(getattr(self.config, "imgsz", 640) or 640),
            conf=float(_num_or(getattr(self.config, "conf", 0.25), 0.25)),
            iou=float(_num_or(getattr(self.config, "iou", 0.7), 0.7)),
            max_det=int(getattr(self.config, "max_det", 300) or 300),
            device=None if device == "auto" else device,
            project=str(out_dir),
            exist_ok=True,
            verbose=False,
        )
        out: list[Any] = []
        for r in results or []:
            boxes, scores, labels = [], [], []
            if getattr(r, "boxes", None) is not None and len(r.boxes):
                xyxy = r.boxes.xyxy.cpu().tolist()
                confs = r.boxes.conf.cpu().tolist()
                clss = r.boxes.cls.cpu().tolist()
                names = getattr(r, "names", None) or {}
                for b, c, cls_id in zip(xyxy, confs, clss):
                    boxes.append(b)
                    scores.append(float(c))
                    labels.append(str(names.get(int(cls_id), int(cls_id))))
            out.append(
                DetectionResult(
                    boxes=boxes,
                    scores=scores,
                    labels=labels,
                    metadata={"backend": "ultralytics", "weights": str(weights)},
                )
            )
        log.info("yolo_predict ultralytics produced %d result(s)", len(out))
        return {"output": out}
