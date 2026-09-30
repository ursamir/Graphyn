"""VideoIngestNode — Ingest video files/folders

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
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

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("video_ingest.types")
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

def _video_files(config) -> list[Path]:
    root = Path(str(_cfg(config, "path", "") or ""))
    exts = {str(e).lower() if str(e).startswith(".") else f".{e}" for e in (_cfg(config, "extensions", [".mp4", ".mov", ".avi", ".mkv"]) or [])}
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    walker = root.rglob("*") if bool(_cfg(config, "recursive", True)) else root.glob("*")
    return [p for p in walker if p.is_file() and (not exts or p.suffix.lower() in exts)]

def _video_sample(types, path: Path):
    return _T(types, "VideoSample", path=str(path), frames=[], fps=0.0, metadata={"bytes": path.stat().st_size})

def _video_ingest(config, inputs, types):
    return [_video_sample(types, p) for p in _video_files(config)]



class VideoIngestNode(Node):
    """Ingest video files/folders"""

    node_type: ClassVar[str] = "video_ingest"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="video_ingest",
        label="Video Ingest",
        description="Ingest video files/folders",
        category="Input",
        version="0.1.0",
        tags=["video"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {}

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[VideoSample] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        path: str = Field(default='', title="Path", description="Path.")
        recursive: bool = Field(default=True, title="Recursive", description="Recursive.")
        extensions: list = Field(default_factory=list)

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'video' / 'video_ingest'
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
            raise ImportError(f"video_ingest: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _video_ingest(self.config, inputs, _types)}
