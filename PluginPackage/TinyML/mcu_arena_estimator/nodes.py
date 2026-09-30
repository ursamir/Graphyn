"""McuArenaEstimatorNode — Tensor arena / peak RAM estimate

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

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
from app.models.tflite_artifact import TFLiteArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("mcu_arena_estimator.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ArenaEstimate = _types.ArenaEstimate

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

def _numbers(obj: Any) -> list[float]:
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("values", "features", "payload", "vector", "embedding", "data"):
            if key in data:
                return _numbers(data[key])
        return [float(v) for v in data.values() if isinstance(v, (int, float))]
    if isinstance(data, (list, tuple)):
        out: list[float] = []
        for item in data:
            if isinstance(item, (int, float)):
                out.append(float(item))
            elif isinstance(item, (list, tuple, dict)):
                out.extend(_numbers(item))
        return out
    if isinstance(data, (int, float)):
        return [float(data)]
    return []

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

def _arena(config, inputs, types):
    raw = _bytes_of(inputs.get("input"))
    # Activation arena is estimated from tensor-shaped numbers in the payload, else from model size.
    nums = _numbers(inputs.get("input"))
    activations = int(sum(abs(n) for n in nums[:8])) if nums else max(1024, len(raw) // 4)
    target = int(float(_cfg(config, "target_ram_kb", 64) or 64) * 1024)
    headroom = float(_cfg(config, "headroom_pct", 20) or 0) / 100
    peak = int(activations * (1 + headroom))
    return _T(types, "ArenaEstimate", arena_bytes=activations, peak_bytes=peak, metadata={"fits": peak <= target, "target_bytes": target, "model_bytes": len(raw)})



class McuArenaEstimatorNode(Node):
    """Tensor arena / peak RAM estimate"""

    node_type: ClassVar[str] = "mcu_arena_estimator"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="mcu_arena_estimator",
        label="Mcu Arena Estimator",
        description="Tensor arena / peak RAM estimate",
        category="Quality",
        version="0.1.0",
        tags=["tinyml"],
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
        "output": OutputPort(name="output", data_type=object, description="ArenaEstimate NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        target_ram_kb: int = Field(default=256, title="Target ram kb", description="Target ram kb.")
        headroom_pct: float = Field(default=15.0, title="Headroom pct", description="Headroom pct.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'mcu_arena_estimator'
        if stub:
            log.warning(
                "%s: stub mode (config.stub=True) returned a placeholder, not a real result",
                getattr(self, "node_type", type(self).__name__),
            )
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            _out = out_dir / 'stub'
            result = ArenaEstimate()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"mcu_arena_estimator: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _arena(self.config, inputs, _types)}
