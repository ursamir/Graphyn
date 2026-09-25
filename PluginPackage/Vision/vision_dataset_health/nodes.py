"""VisionDatasetHealthNode — Class balance / box size health

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

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("vision_dataset_health.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DatasetHealthReport = _types.DatasetHealthReport
ImageSample = _types.ImageSample
VisionDatasetArtifact = _types.VisionDatasetArtifact

log = logging.getLogger(__name__)


class VisionDatasetHealthNode(Node):
    """Class balance / box size health"""

    node_type: ClassVar[str] = "vision_dataset_health"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="vision_dataset_health",
        label="Vision Dataset Health",
        description="Class balance / box size health",
        category="Quality",
        version="0.1.0",
        tags=["vision", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[ImageSample] NEW|VisionDatasetArtifact NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DatasetHealthReport NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        min_per_class: int = Field(default=20, title="Min per class", description="Min per class.")
        flag_empty_images: bool = Field(default=True, title="Flag empty images", description="Flag empty images.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'vision' / 'vision_dataset_health'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = DatasetHealthReport()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"vision_dataset_health: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'vision' / 'vision_dataset_health'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": DatasetHealthReport()}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
