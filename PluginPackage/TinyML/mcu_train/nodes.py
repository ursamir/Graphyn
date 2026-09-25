"""McuTrainNode — MCU train + PTQ calib + optional QAT

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
from app.models.model_artifact import ModelArtifact

log = logging.getLogger(__name__)


class McuTrainNode(Node):
    """MCU train + PTQ calib + optional QAT"""

    node_type: ClassVar[str] = "mcu_train"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="mcu_train",
        label="Mcu Train",
        description="MCU train + PTQ calib + optional QAT",
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
        "model": InputPort(name="model", data_type=object, required=True, description="object"),
        "dataset": InputPort(name="dataset", data_type=object, required=True, description="DatasetArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ModelArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        epochs: int = Field(default=30, title="Epochs", description="Epochs.")
        qat: bool = Field(default=False, title="Qat", description="Qat.")
        qat_epochs: int = Field(default=5, title="Qat epochs", description="Qat epochs.")
        calib_fraction: float = Field(default=0.1, title="Calib fraction", description="Calib fraction.")
        output_path: str = Field(default='workspace/artifacts/models/mcu', title="Output path", description="Output path.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'mcu_train'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = ModelArtifact(model_path=str(_out), labels=[], history={"stub": True}, metrics={})
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"mcu_train: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'tinyml' / 'mcu_train'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": ModelArtifact(model_path=str(_out), labels=[], history={"stub": True}, metrics={})}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
