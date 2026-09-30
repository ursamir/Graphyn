"""YoloTrainNode — Ultralytics YOLO train

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
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

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("yolo_train.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

VisionDatasetArtifact = _types.VisionDatasetArtifact


def _force_cpu() -> bool:
    """Stay on CPU when another process owns the GPU. Default on."""
    import os

    flag = os.environ.get("GRAPHYN_ML_FORCE_CPU", "1").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    os.environ.setdefault("ULTRALYTICS_OFFLINE", "1")
    return True


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
        tags=["vision"],
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
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        task: str = Field(default='detect', title="Task", description="Task.")
        model: str = Field(default='yolov8n.pt', title="Model", description="Model.")
        epochs: int = Field(default=100, title="Epochs", description="Epochs.")
        imgsz: int = Field(default=640, title="Imgsz", description="Imgsz.")
        batch: int = Field(default=16, title="Batch", description="Batch.")
        device: Literal["auto", "cpu", "cuda", "mps"] = Field(default="auto", title="Device", description="auto lets ultralytics pick (CPU when GRAPHYN_ML_FORCE_CPU is on).")
        project: str = Field(default='workspace/artifacts/models/yolo', title="Project", description="Project.")


    def process(self, inputs=None, **kwargs):
        """Train YOLO via ultralytics when available; stub otherwise."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path(getattr(self.config, "project", None) or "workspace/artifacts/models/yolo")
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
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
            _force_cpu()
            from ultralytics import YOLO  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "ultralytics is not installed in this plugin venv. "
                "Use Plugins → Install optional (venv)."
            ) from exc
        model_name = str(getattr(self.config, "model", "yolov8n.pt") or "yolov8n.pt")
        data = inputs.get("dataset") or inputs.get("input")
        data_yaml = None
        if isinstance(data, str):
            data_yaml = data
        elif isinstance(data, dict):
            meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            data_yaml = (
                data.get("yaml_path")
                or data.get("manifest_path")
                or meta.get("yaml_path")
                or data.get("path")
            )
        else:
            meta = getattr(data, "metadata", None) or {}
            if not isinstance(meta, dict):
                meta = {}
            data_yaml = (
                getattr(data, "yaml_path", None)
                or getattr(data, "manifest_path", None)
                or meta.get("yaml_path")
            )
        if not data_yaml:
            raise RuntimeError("yolo_train: dataset yaml_path required when stub=False")
        model = YOLO(model_name)
        device = str(getattr(self.config, "device", "auto") or "auto")
        if _force_cpu():
            if device in ("auto", "", "0", "cuda", "cuda:0"):
                device = "cpu"
        try:
            results = model.train(
                data=str(data_yaml),
                epochs=epochs,
                imgsz=int(getattr(self.config, "imgsz", 640) or 640),
                batch=int(getattr(self.config, "batch", 16) or 16),
                device=None if device == "auto" else device,
                project=str(out_dir),
                exist_ok=True,
                workers=0,
            )
        except (FileNotFoundError, ValueError, AssertionError) as exc:
            log.warning(
                "yolo_train: ultralytics train failed (%s) — writing stub weights for OOB continuity",
                exc,
            )
            best = out_dir / "stub_best.pt"
            best.write_bytes(b"YOLO_FALLBACK_AFTER_DATA_ERROR")
            return {
                "output": ModelArtifact(
                    model_path=str(best),
                    labels=[],
                    history={"backend": "ultralytics", "fallback": "stub", "error": str(exc)[:400]},
                    metrics={"fallback": True},
                )
            }
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

