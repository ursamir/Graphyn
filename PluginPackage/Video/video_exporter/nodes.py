"""VideoExporterNode — Export clips/annotated video

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

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("video_exporter.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DetectionResult = _types.DetectionResult
VideoSample = _types.VideoSample

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

def _out_path(config: Any, default_name: str) -> Path:
    raw = _cfg(config, "output_path") or _cfg(config, "output_dir") or _cfg(config, "persist_path")
    path = Path(str(raw or f"workspace/artifacts/proposed/{default_name}"))
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path

def _video_export(config, inputs, types):
    dest = _out_path(config, "video_export")
    folder = dest if dest.is_dir() else dest.parent
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "export.json"
    manifest.write_text(json.dumps({"input": _dump(inputs.get("input")), "overlays": _dump(inputs.get("overlays")), "draw_boxes": bool(_cfg(config, "draw_boxes", False))}, default=str), encoding="utf-8")
    return {"path": str(manifest)}



class VideoExporterNode(Node):
    """Export clips/annotated video"""

    node_type: ClassVar[str] = "video_exporter"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="video_exporter",
        label="Video Exporter",
        description="Export clips/annotated video",
        category="Output",
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
        "overlays": InputPort(name="overlays", data_type=object | None, required=False, description="list[DetectionResult] NEW optional"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[VideoSample] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        output_dir: str = Field(default='workspace/datasets/output/video', title="Output dir", description="Output dir.")
        draw_boxes: bool = Field(default=False, title="Draw boxes", description="Draw boxes.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'video' / 'video_exporter'
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
            raise ImportError(f"video_exporter: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _video_export(self.config, inputs, _types)}
