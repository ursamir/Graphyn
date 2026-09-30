"""TflmOpSupportCheckNode — Check ops vs TFLM kernel allowlist

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json
import re

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

def _tflm_ops(config, inputs, types):
    raw = _bytes_of(inputs.get("input"))
    # TFLite builtin opcode names we can recognize in the flatbuffer strings.
    known = {
        "ADD", "MUL", "CONV_2D", "CONV2D", "DEPTHWISE_CONV_2D", "DEPTHWISE_CONV2D",
        "FULLY_CONNECTED", "SOFTMAX", "RESHAPE", "MAX_POOL_2D", "AVERAGE_POOL_2D",
        "LOGISTIC", "RELU", "MEAN", "PAD", "CONCATENATION", "TRANSPOSE",
    }
    text = raw.decode("latin1", errors="ignore")
    found = sorted({op for op in known if op in text})
    # Only treat TFLite-looking opcode tokens as candidates (skip binary noise).
    candidates = re.findall(r"\b(?:[A-Z][A-Z0-9_]{2,})\b", text)
    unsupported = [op for op in candidates if op not in known]
    unsupported = sorted(set(unsupported))[:40]
    fail = bool(_cfg(config, "fail_on_unsupported", False))
    supported = not unsupported
    if fail and unsupported:
        raise RuntimeError("unsupported TFLite ops: " + ", ".join(unsupported[:10]))
    return _T(types, "TflmSupportReport", supported=supported, unsupported_ops=unsupported, metadata={"known_ops": found, "tflm_version": str(_cfg(config, "tflm_version", ""))})



class TflmOpSupportCheckNode(Node):
    """Check ops vs TFLM kernel allowlist"""

    node_type: ClassVar[str] = "tflm_op_support_check"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="tflm_op_support_check",
        label="Tflm Op Support Check",
        description="Check ops vs TFLM kernel allowlist",
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
        "output": OutputPort(name="output", data_type=object, description="TflmSupportReport NEW"),
        "artifact": OutputPort(name="artifact", data_type=object, description="DeploymentArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        tflm_version: str = Field(default='latest', title="Tflm version", description="Tflm version.")
        fail_on_unsupported: bool = Field(default=True, title="Fail on unsupported", description="Fail on unsupported.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'tflm_op_support_check'
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
        """Run this node's real implementation."""
        return {"output": _tflm_ops(self.config, inputs, _types)}
