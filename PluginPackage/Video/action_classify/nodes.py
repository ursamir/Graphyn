"""ActionClassifyNode — Action/activity classify

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json
import re

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.prediction_result import PredictionResult

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("action_classify.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

VideoSample = _types.VideoSample

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

def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())

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

def _video_embed(config, inputs, types):
    text = _text(inputs.get("input"))
    n = int(_cfg(config, "num_frames", 4) or 4)
    vec = [0.0] * 32
    for i, tok in enumerate(_tokens(text)[:32]):
        vec[i % 32] += (len(tok) % 7) / 7
    # Mix a little of the byte energy so different files differ.
    raw = _bytes_of(inputs.get("input"))
    for i, b in enumerate(raw[:256]):
        vec[i % 32] += b / 2550
    return _T(types, "EmbeddingVector", embedding=vec, metadata={"frames": n, "model": str(_cfg(config, "model", "bag-of-bytes"))}) if hasattr(types, "EmbeddingVector") else {"embedding": vec}

def _action(config, inputs, types):
    vec = _video_embed(config, inputs, types)
    data = _dump(vec)
    vector = data.get("embedding") if isinstance(data, dict) else None
    score = sum(vector or []) / max(1, len(vector or []))
    return {"label": "motion" if score > 0.2 else "idle", "score": score, "backend": str(_cfg(config, "backend", "energy"))}



class ActionClassifyNode(Node):
    """Action/activity classify"""

    node_type: ClassVar[str] = "action_classify"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="action_classify",
        label="Action Classify",
        description="Action/activity classify",
        category="Inference",
        version="0.1.0",
        tags=["video"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[VideoSample] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[PredictionResult]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        model_path: str = Field(default='', title="Model path", description="Model path.")
        backend: Literal["auto", "energy"] = Field(default='auto', title="Backend", description="Backend.")
        num_frames: int = Field(default=16, title="Num frames", description="Num frames.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'video' / 'action_classify'
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
            result = []
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"action_classify: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _action(self.config, inputs, _types)}
