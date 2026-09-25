"""McuFeaturePipelineNode — MCU-RAM MFCC/spectrogram/IMU features

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

from app.models.feature_array import FeatureArray

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("mcu_feature_pipeline.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

McuSample = _types.McuSample

log = logging.getLogger(__name__)


class McuFeaturePipelineNode(Node):
    """MCU-RAM MFCC/spectrogram/IMU features"""

    node_type: ClassVar[str] = "mcu_feature_pipeline"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="mcu_feature_pipeline",
        label="Mcu Feature Pipeline",
        description="MCU-RAM MFCC/spectrogram/IMU features",
        category="Features",
        version="0.1.0",
        tags=["tinyml", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[McuSample] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[FeatureArray]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        feature_type: str = Field(default='mfcc', title="Feature type", description="Feature type.")
        n_mfcc: int = Field(default=10, title="N mfcc", description="N mfcc.")
        n_mels: int = Field(default=40, title="N mels", description="N mels.")
        fixed_length: int = Field(default=49, title="Fixed length", description="Fixed length.")
        max_ram_kb: int = Field(default=256, title="Max ram kb", description="Max ram kb.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'mcu_feature_pipeline'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = []
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"mcu_feature_pipeline: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'tinyml' / 'mcu_feature_pipeline'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": []}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
