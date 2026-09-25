"""VideoCaptionNode — VL caption for clips/frames

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=True returns typed minimal outputs without heavy deps.
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
        _types = importlib.import_module("video_caption.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

CaptionRecord = _types.CaptionRecord
ImageSample = _types.ImageSample
VideoSample = _types.VideoSample

log = logging.getLogger(__name__)


class VideoCaptionNode(Node):
    """VL caption for clips/frames"""

    node_type: ClassVar[str] = "video_caption"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="video_caption",
        label="Video Caption",
        description="VL caption for clips/frames",
        category="Generation",
        version="0.1.0",
        tags=["video", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[VideoSample] NEW|list[ImageSample] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[str]"),
        "captions": OutputPort(name="captions", data_type=object, description="list[CaptionRecord] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        backend: str = Field(default='blip', title="Backend", description="Backend.")
        api_secret_name: str = Field(default='OPENAI_API_KEY', title="Api secret name", description="Api secret name.")
        max_frames: int = Field(default=8, title="Max frames", description="Max frames.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'video' / 'video_caption'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = {
                "output": [],
                "captions": [],
            }
            return result
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"video_caption: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

    def _process_real(self, inputs: dict):
        """Override point for richer backends; default = stub path."""
        # Keep default identical to stub so unit tests stay offline.
        prev = self.config.stub
        object.__setattr__(self.config, 'stub', True) if hasattr(self.config, 'model_copy') else None
        try:
            self.config.stub = True  # type: ignore[misc]
        except Exception:
            pass
        try:
            # Re-enter stub branch
            out_dir = Path('workspace/artifacts') / 'video' / 'video_caption'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {
                "output": [],
                "captions": [],
            }
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
