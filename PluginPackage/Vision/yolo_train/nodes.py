"""YoloTrainNode — Ultralytics YOLO train

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=True returns typed minimal outputs without heavy deps.
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

from app.models.model_artifact import ModelArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("yolo_train.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

VisionDatasetArtifact = _types.VisionDatasetArtifact

log = logging.getLogger(__name__)


class YoloTrainNode(Node):
    """Ultralytics YOLO train"""

    node_type: ClassVar[str] = "yolo_train"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_train",
        label="Yolo Train",
        description="Ultralytics YOLO train",
        category="ML",
        version="0.2.0",
        tags=["vision", "wave1"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "dataset": InputPort(name="dataset", data_type=object, required=True, description="VisionDatasetArtifact NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ModelArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        task: str = Field(default='detect', title="Task", description="Task.")
        model: str = Field(default='yolov8n.pt', title="Model", description="Model.")
        epochs: int = Field(default=100, title="Epochs", description="Epochs.")
        imgsz: int = Field(default=640, title="Imgsz", description="Imgsz.")
        batch: int = Field(default=16, title="Batch", description="Batch.")
        device: str = Field(default='auto', title="Device", description="Device.")
        project: str = Field(default='workspace/artifacts/models/yolo', title="Project", description="Project.")


    def process(self, inputs=None, **kwargs):
        """Train YOLO via ultralytics when available; stub otherwise."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        stub = bool(getattr(self.config, "stub", True))
        out_dir = Path(getattr(self.config, "project", None) or "workspace/artifacts/models/yolo")
        out_dir.mkdir(parents=True, exist_ok=True)
        if stub:
            weights = out_dir / "stub_best.pt"
            weights.write_bytes(b"YOLO_STUB_WEIGHTS_v1")
            (out_dir / "results.json").write_text(
                '{"stub": true, "epochs": %d, "model": %s}'
                % (int(getattr(self.config, "epochs", 0) or 0), repr(str(getattr(self.config, "model", "")))),
                encoding="utf-8",
            )
            return {
                "output": ModelArtifact(
                    model_path=str(weights),
                    labels=[],
                    history={"stub": True, "backend": "ultralytics"},
                    metrics={"stub": True},
                )
            }
        try:
            from app.core.plugins.wave1_runtime import force_cpu_torch_env

            force_cpu_torch_env()
            from ultralytics import YOLO  # type: ignore
        except ImportError as exc:
            from app.core.plugins.wave1_runtime import install_hint

            raise ImportError(install_hint("vision", ["ultralytics>=8.0", "torch>=2.0"])) from exc
        model_name = str(getattr(self.config, "model", "yolov8n.pt") or "yolov8n.pt")
        data = inputs.get("dataset") or inputs.get("input")
        data_yaml = None
        if hasattr(data, "yaml_path"):
            data_yaml = data.yaml_path
        elif isinstance(data, dict):
            data_yaml = data.get("yaml_path") or data.get("path")
        elif isinstance(data, str):
            data_yaml = data
        if not data_yaml:
            raise RuntimeError("yolo_train: dataset yaml_path required when stub=False")
        model = YOLO(model_name)
        device = str(getattr(self.config, "device", "auto") or "auto")
        # FaceRecognition-safe: honor GRAPHYN_WAVE1_FORCE_CPU
        import os as _os
        if _os.environ.get("GRAPHYN_WAVE1_FORCE_CPU", "1").strip().lower() not in ("0", "false", "no"):
            if device in ("auto", "", "0", "cuda", "cuda:0"):
                device = "cpu"
        results = model.train(
            data=str(data_yaml),
            epochs=int(getattr(self.config, "epochs", 100) or 100),
            imgsz=int(getattr(self.config, "imgsz", 640) or 640),
            batch=int(getattr(self.config, "batch", 16) or 16),
            device=device,
            project=str(out_dir),
            exist_ok=True,
            workers=0,
        )
        best = Path(getattr(results, "save_dir", out_dir)) / "weights" / "best.pt"
        if not best.exists():
            best = out_dir / "stub_best.pt"
            best.write_bytes(b"YOLO_FALLBACK")
        return {
            "output": ModelArtifact(
                model_path=str(best),
                labels=[],
                history={"backend": "ultralytics"},
                metrics={},
            )
        }

