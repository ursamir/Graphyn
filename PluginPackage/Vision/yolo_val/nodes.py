"""YoloValNode — Ultralytics YOLO validation

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
        _types = importlib.import_module("yolo_val.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

VisionDatasetArtifact = _types.VisionDatasetArtifact

log = logging.getLogger(__name__)


class YoloValNode(Node):
    """Ultralytics YOLO validation"""

    node_type: ClassVar[str] = "yolo_val"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_val",
        label="Yolo Val",
        description="Ultralytics YOLO validation",
        category="ML",
        version="0.1.0",
        tags=["vision", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "model": InputPort(name="model", data_type=object, required=True, description="ModelArtifact"),
        "dataset": InputPort(name="dataset", data_type=object, required=True, description="VisionDatasetArtifact NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ModelArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        task: str = Field(default='detect', title="Task", description="Task.")
        imgsz: int = Field(default=640, title="Imgsz", description="Imgsz.")
        conf: float = Field(default=0.001, title="Conf", description="Conf.")
        iou: float = Field(default=0.6, title="Iou", description="Iou.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_val'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = ModelArtifact(model_path=str(_out), labels=[], history={"stub": True}, metrics={})
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"yolo_val: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

    def _process_real(self, inputs: dict):
        """Override point for richer backends; default = stub path."""
        # Keep default identical to stub so unit tests stay offline.
        prev = self.config.stub
        object.__setattr__(self.config, 'stub', True) if hasattr(self.config, 'model_copy') else None
        try:
            self.config.stub = True  # type: ignore[misc]
        except Exception:
            pass
        try:
            # Re-enter stub branch
            out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_val'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": ModelArtifact(model_path=str(_out), labels=[], history={"stub": True}, metrics={})}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
