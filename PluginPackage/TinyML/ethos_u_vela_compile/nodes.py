"""EthosUVelaCompileNode — Arm Vela compile for Ethos-U (needs-tool)

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import hashlib
import json
import shutil

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
        _types = importlib.import_module("ethos_u_vela_compile.types")
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

def _vela_or_copy(config, inputs, types, tool: str):
    raw = _bytes_of(inputs.get("input"))
    dest = _out_path(config, tool)
    out = dest / f"model.{tool}" if dest.is_dir() else dest
    out.parent.mkdir(parents=True, exist_ok=True)
    binary = shutil.which(str(_cfg(config, "vela_bin", tool) or tool))
    src = _dump(inputs.get("input"))
    src_path = src.get("path") if isinstance(src, dict) else None
    if binary and src_path and Path(str(src_path)).is_file():
        import subprocess

        proc = subprocess.run([binary, str(src_path), "-o", str(out)], capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"{tool} failed: {proc.stderr.strip()[:500]}")
        return {"path": str(out), "tool": binary}
    out.write_bytes(raw)
    (out.with_suffix(out.suffix + ".json")).write_text(
        json.dumps({"tool": tool, "sha256": _sha(raw, "sha256"), "bytes": len(raw), "compiled_with": "byte-preserving (compiler binary not on PATH)"}),
        encoding="utf-8",
    )
    return {"path": str(out), "bytes": len(raw), "compiler": "unavailable", "sha256": _sha(raw, "sha256")}

def _impl(config, inputs, types):
    return _vela_or_copy(config, inputs, types, "vela")



class EthosUVelaCompileNode(Node):
    """Arm Vela compile for Ethos-U (needs-tool)"""

    node_type: ClassVar[str] = "ethos_u_vela_compile"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="ethos_u_vela_compile",
        label="Ethos U Vela Compile",
        description="Arm Vela compile for Ethos-U (needs-tool)",
        category="ML",
        version="0.1.0",
        tags=["tinyml"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="TFLiteArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DeploymentArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        accelerator: str = Field(default='ethos-u55-128', title="Accelerator", description="Accelerator.")
        system_config: str = Field(default='Ethos_U55_High_End_Embedded', title="System config", description="System config.")
        vela_bin: str = Field(default='vela', title="Vela bin", description="Vela bin.")
        output_path: str = Field(default='workspace/artifacts/optimized/vela', title="Output path", description="Output path.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'ethos_u_vela_compile'
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
            raise ImportError(f"ethos_u_vela_compile: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _impl(self.config, inputs, _types)}
