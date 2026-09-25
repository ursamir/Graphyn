"""TflmOpSupportCheckNode — Check ops vs TFLM kernel allowlist

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
from app.models.tflite_artifact import TFLiteArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("tflm_op_support_check.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

TflmSupportReport = _types.TflmSupportReport

log = logging.getLogger(__name__)


class TflmOpSupportCheckNode(Node):
    """Check ops vs TFLM kernel allowlist"""

    node_type: ClassVar[str] = "tflm_op_support_check"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="tflm_op_support_check",
        label="Tflm Op Support Check",
        description="Check ops vs TFLM kernel allowlist",
        category="Quality",
        version="0.1.0",
        tags=["tinyml", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="TFLiteArtifact|DeploymentArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="TflmSupportReport NEW"),
        "artifact": OutputPort(name="artifact", data_type=object, description="DeploymentArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        tflm_version: str = Field(default='latest', title="Tflm version", description="Tflm version.")
        fail_on_unsupported: bool = Field(default=True, title="Fail on unsupported", description="Fail on unsupported.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'tflm_op_support_check'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = {
                "output": TflmSupportReport(),
                "artifact": DeploymentArtifact(package_path=str(_out), target="stub", metadata={"stub": True}),
            }
            return result
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"tflm_op_support_check: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'tinyml' / 'tflm_op_support_check'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {
                "output": TflmSupportReport(),
                "artifact": DeploymentArtifact(package_path=str(_out), target="stub", metadata={"stub": True}),
            }
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
