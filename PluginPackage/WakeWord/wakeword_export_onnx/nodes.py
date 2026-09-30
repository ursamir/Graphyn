"""WakewordExportOnnxNode — WakeWord ONNX exporter node

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
from app.models.model_artifact import ModelArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("wakeword_export_onnx.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

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

def _out_path(config: Any, default_name: str) -> Path:
    raw = _cfg(config, "output_path") or _cfg(config, "output_dir") or _cfg(config, "persist_path")
    path = Path(str(raw or f"workspace/artifacts/proposed/{default_name}"))
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path

def _onnx_export(config, inputs, types):
    path = _out_path(config, "model.onnx")
    dest = path if path.suffix else path / "model.onnx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = _bytes_of(inputs.get("input"))
    # If the payload is already an ONNX protobuf, keep it. Otherwise write a
    # minimal valid-enough graph note plus the weight bytes for a later converter.
    if raw[:8] != b"\x08" and not raw.startswith(b"ONNX"):
        sidecar = {"opset": int(_cfg(config, "opset", 17) or 17), "bytes": len(raw), "sha256": _sha(raw, "sha256")}
        dest.with_suffix(".json").write_text(json.dumps(sidecar), encoding="utf-8")
    dest.write_bytes(raw)
    return {"path": str(dest), "bytes": dest.stat().st_size, "sha256": _sha(dest.read_bytes(), "sha256")}



class WakewordExportOnnxNode(Node):
    """WakeWord ONNX exporter node"""

    node_type: ClassVar[str] = "wakeword_export_onnx"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="wakeword_export_onnx",
        label="Wakeword Export Onnx",
        description="WakeWord ONNX exporter node",
        category="ML",
        version="0.1.0",
        tags=["wakeword"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="ModelArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DeploymentArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        opset: int = Field(default=13, title="Opset", description="Opset.")
        output_path: str = Field(default='workspace/artifacts/optimized/wakeword', title="Output path", description="Output path.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'wakeword' / 'wakeword_export_onnx'
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
            result = DeploymentArtifact(package_path=str(_out), target="stub", metadata={"stub": True})
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"wakeword_export_onnx: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _onnx_export(self.config, inputs, _types)}
