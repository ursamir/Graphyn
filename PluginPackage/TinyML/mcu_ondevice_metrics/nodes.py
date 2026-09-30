"""McuOndeviceMetricsNode — On-device metrics placeholder (needs-API)

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import hashlib
import json

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

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _T(types: Any, name: str, **kwargs: Any) -> Any:
    cls = getattr(types, name, None) if types is not None else None
    if cls is None:
        return kwargs
    fields = getattr(cls, "model_fields", None)
    if isinstance(fields, dict) and fields:
        kwargs = {k: v for k, v in kwargs.items() if k in fields}
    return cls(**kwargs)

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj

def _text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list):
        return "\n".join(_text(x) for x in obj)
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("text", "query", "content", "answer", "user", "path", "value", "final"):
            if data.get(key):
                return str(data[key])
        return json.dumps(data, default=str)
    return str(obj)

def _sha(data: bytes, algo: str) -> str:
    h = hashlib.new(algo if algo in hashlib.algorithms_available else "sha256")
    h.update(data)
    return h.hexdigest()

def _bytes_of(obj: Any) -> bytes:
    if isinstance(obj, bytes):
        return obj
    data = _dump(obj)
    if isinstance(data, dict) and isinstance(data.get("bytes"), (bytes, bytearray)):
        return bytes(data["bytes"])
    if isinstance(data, dict) and data.get("path"):
        path = Path(str(data["path"]))
        if path.is_file():
            return path.read_bytes()
    return _text(obj).encode("utf-8")

def _ondevice(config, inputs, types):
    raw = _bytes_of(inputs.get("input"))
    dry = bool(_cfg(config, "dry_run", True))
    metrics = {"bytes": len(raw), "sha256": _sha(raw, "sha256")}
    if not dry:
        raise RuntimeError("mcu_ondevice_metrics: no device telemetry source is connected. Refusing to invent on-device numbers.")
    return _T(
        types,
        "OnDeviceMetrics",
        status="host-estimated",
        metrics=metrics,
        message="Host-side size/hash of the artifact. Not device telemetry.",
        metadata={"dry_run": True},
    )



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
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in honesty placeholder. Default reports host-estimated metrics and does not claim device telemetry.")
        device_id: str = Field(default='', title="Device id", description="Device id.")
        dry_run: bool = Field(default=True, title="Dry run", description="Dry run.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, "stub", False))
        if not stub:
            return {"output": _ondevice(self.config, inputs, _types)}

        # Explicit stub=True keeps the needs-api receipt and never claims device telemetry.
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
