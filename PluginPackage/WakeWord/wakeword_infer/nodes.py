"""WakewordInferNode — WakeWord realtime infer node

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

from app.models.audio_sample import AudioSample
from app.models.feature_array import FeatureArray
from app.models.prediction_result import PredictionResult

log = logging.getLogger(__name__)


class WakewordInferNode(Node):
    """WakeWord realtime infer node"""

    node_type: ClassVar[str] = "wakeword_infer"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="wakeword_infer",
        label="Wakeword Infer",
        description="WakeWord realtime infer node",
        category="Inference",
        version="0.1.0",
        tags=["wakeword", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[FeatureArray]|list[AudioSample]"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[PredictionResult]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        model_path: str = Field(default='', title="Model path", description="Model path.")
        threshold: float = Field(default=0.8, title="Threshold", description="Threshold.")
        backend: str = Field(default='auto', title="Backend", description="Backend.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'wakeword' / 'wakeword_infer'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = []
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"wakeword_infer: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'wakeword' / 'wakeword_infer'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": []}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
