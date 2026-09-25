"""McuModelZooNode — DS-CNN/MobileNetTiny/MCUNet/KWS zoo

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

from app.models.dataset_artifact import DatasetArtifact

log = logging.getLogger(__name__)


class McuModelZooNode(Node):
    """DS-CNN/MobileNetTiny/MCUNet/KWS zoo"""

    node_type: ClassVar[str] = "mcu_model_zoo"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="mcu_model_zoo",
        label="Mcu Model Zoo",
        description="DS-CNN/MobileNetTiny/MCUNet/KWS zoo",
        category="ML",
        version="0.1.0",
        tags=["tinyml", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="DatasetArtifact|object"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="object"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        architecture: str = Field(default='ds_cnn', title="Architecture", description="Architecture.")
        num_classes: int = Field(default=12, title="Num classes", description="Num classes.")
        input_shape: list = Field(default_factory=lambda: [49, 10, 1])
        width_multiplier: float = Field(default=0.25, title="Width multiplier", description="Width multiplier.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'mcu_model_zoo'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = None
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"mcu_model_zoo: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'tinyml' / 'mcu_model_zoo'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": None}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
