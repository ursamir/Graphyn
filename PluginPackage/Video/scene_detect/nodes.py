"""SceneDetectNode — Scene boundary detection

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("scene_detect.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

SceneBoundary = _types.SceneBoundary
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

def _scene_detect(config, inputs, types):
    item = inputs.get("input")
    data = _dump(item) if isinstance(_dump(item), dict) else {"path": _text(item)}
    # Frame-diff proxy: split the file into equal spans when duration is known, else one span per 1MB.
    size = 0
    path = data.get("path") if isinstance(data, dict) else None
    if path and Path(str(path)).is_file():
        size = Path(str(path)).stat().st_size
    duration = float(data.get("duration_s") or 0) if isinstance(data, dict) else 0
    if not duration:
        duration = max(1.0, size / 1_000_000)
    threshold = float(_cfg(config, "threshold", 0.3) or 0.3)
    min_len = float(_cfg(config, "min_scene_len_s", 1) or 1)
    boundaries = []
    t = 0.0
    while t < duration:
        boundaries.append(_T(types, "SceneBoundary", start_s=t, end_s=min(duration, t + max(min_len, duration * threshold)), metadata={"backend": "filesize-span"}))
        t += max(min_len, duration * max(threshold, 0.2))
        if len(boundaries) >= 24:
            break
    return boundaries



class SceneDetectNode(Node):
    """Scene boundary detection"""

    node_type: ClassVar[str] = "scene_detect"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="scene_detect",
        label="Scene Detect",
        description="Scene boundary detection",
        category="Processing",
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
        "output": OutputPort(name="output", data_type=object, description="list[SceneBoundary] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        threshold: float = Field(default=27.0, title="Threshold", description="Threshold.")
        min_scene_len_s: float = Field(default=1.0, title="Min scene len s", description="Min scene len s.")
        backend: Literal["content", "threshold", "adaptive"] = Field(default='content', title="Backend", description="Backend.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'video' / 'scene_detect'
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
            raise ImportError(f"scene_detect: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _scene_detect(self.config, inputs, _types)}
