"""YoloExportNode — Export onnx/engine/coreml/openvino/tflite/ncnn/rknn

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

from app.models.deployment_artifact import DeploymentArtifact
from app.models.model_artifact import ModelArtifact

log = logging.getLogger(__name__)


class YoloExportNode(Node):
    """Export onnx/engine/coreml/openvino/tflite/ncnn/rknn"""

    node_type: ClassVar[str] = "yolo_export"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_export",
        label="Yolo Export",
        description="Export onnx/engine/coreml/openvino/tflite/ncnn/rknn",
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
        "input": InputPort(name="input", data_type=object, required=True, description="ModelArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DeploymentArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        format: str = Field(default='onnx', title="Format", description="Format.")
        imgsz: int = Field(default=640, title="Imgsz", description="Imgsz.")
        half: bool = Field(default=False, title="Half", description="Half.")
        int8: bool = Field(default=False, title="Int8", description="Int8.")
        nms: bool = Field(default=True, title="Nms", description="Nms.")
        output_path: str = Field(default='workspace/artifacts/optimized/yolo', title="Output path", description="Output path.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_export'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = DeploymentArtifact(package_path=str(_out), target="stub", metadata={"stub": True})
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"yolo_export: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_export'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": DeploymentArtifact(package_path=str(_out), target="stub", metadata={"stub": True})}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
