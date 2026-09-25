"""TinymlPtqCalibBuilderNode — Build PTQ representative set

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


class TinymlPtqCalibBuilderNode(Node):
    """Build PTQ representative set"""

    node_type: ClassVar[str] = "tinyml_ptq_calib_builder"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="tinyml_ptq_calib_builder",
        label="Tinyml Ptq Calib Builder",
        description="Build PTQ representative set",
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
        "input": InputPort(name="input", data_type=object, required=True, description="DatasetArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DatasetArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        max_samples: int = Field(default=100, title="Max samples", description="Max samples.")
        stratify: bool = Field(default=True, title="Stratify", description="Stratify.")
        seed: int = Field(default=42, title="Seed", description="Seed.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'tinyml_ptq_calib_builder'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = DatasetArtifact(labels=[], input_shape=(), n_classes=0, metadata={"stub": True})
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"tinyml_ptq_calib_builder: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'tinyml' / 'tinyml_ptq_calib_builder'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": DatasetArtifact(labels=[], input_shape=(), n_classes=0, metadata={"stub": True})}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
