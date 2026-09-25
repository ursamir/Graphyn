"""McuOndeviceMetricsNode — On-device metrics placeholder (needs-API)

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

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("mcu_ondevice_metrics.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

OnDeviceMetrics = _types.OnDeviceMetrics

log = logging.getLogger(__name__)


class McuOndeviceMetricsNode(Node):
    """On-device metrics placeholder (needs-API)"""

    node_type: ClassVar[str] = "mcu_ondevice_metrics"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="mcu_ondevice_metrics",
        label="Mcu Ondevice Metrics",
        description="On-device metrics placeholder (needs-API)",
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
        "input": InputPort(name="input", data_type=object, required=True, description="DeploymentArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="OnDeviceMetrics NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        device_id: str = Field(default='', title="Device id", description="Device id.")
        dry_run: bool = Field(default=True, title="Dry run", description="Dry run.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        # Honesty stub — never fake device flash / on-device metrics.
        dry = bool(getattr(self.config, 'dry_run', True))
        metrics = OnDeviceMetrics(
            status="needs-api",
            metrics={},
            message="On-device metrics require Devices API — not faked.",
            metadata={"dry_run": dry, "node_type": "mcu_ondevice_metrics"},
        )
        if not dry:
            raise RuntimeError(metrics.message + " Set config.dry_run=True for honesty stub.")
        log.warning("mcu_ondevice_metrics: %s", metrics.message)
        return {"output": metrics}
