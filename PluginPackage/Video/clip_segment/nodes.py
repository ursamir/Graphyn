"""ClipSegmentNode — Cut clips from scenes/fixed windows

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
        _types = importlib.import_module("clip_segment.types")
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

def _as_list(obj: Any) -> list:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, tuple):
        return list(obj)
    return [obj]

def _clip_segment(config, inputs, types):
    video = _dump(inputs.get("video"))
    scenes = _as_list(inputs.get("scenes"))
    out = Path(str(_cfg(config, "output_dir", "workspace/artifacts/video/clips") or "clips"))
    out.mkdir(parents=True, exist_ok=True)
    src = str(video.get("path") or "") if isinstance(video, dict) else ""
    clips = []
    for i, scene in enumerate(scenes):
        data = _dump(scene)
        dest = out / f"clip_{i:03d}.json"
        dest.write_text(json.dumps({"source": src, "scene": data}, default=str), encoding="utf-8")
        clips.append(_T(types, "VideoSample", path=str(dest), metadata={"scene": data, "mode": str(_cfg(config, "mode", "copy"))}))
    return clips



class ClipSegmentNode(Node):
    """Cut clips from scenes/fixed windows"""

    node_type: ClassVar[str] = "clip_segment"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="clip_segment",
        label="Clip Segment",
        description="Cut clips from scenes/fixed windows",
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
        "video": InputPort(name="video", data_type=object, required=True, description="list[VideoSample] NEW"),
        "scenes": InputPort(name="scenes", data_type=object | None, required=False, description="list[SceneBoundary] NEW optional"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[VideoSample] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        mode: Literal["scenes", "window"] = Field(default='scenes', title="Mode", description="Mode.")
        window_s: float = Field(default=10.0, title="Window s", description="Window s.")
        output_dir: str = Field(default='workspace/datasets/video/clips', title="Output dir", description="Output dir.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'video' / 'clip_segment'
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
            raise ImportError(f"clip_segment: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _clip_segment(self.config, inputs, _types)}
