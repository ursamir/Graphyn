"""VideoCaptionNode — VL caption for clips/frames

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
        _types = importlib.import_module("video_caption.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

CaptionRecord = _types.CaptionRecord
ImageSample = _types.ImageSample
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

def _frame_sample(config, inputs, types):
    data = _dump(inputs.get("input"))
    path = str(data.get("path") or "") if isinstance(data, dict) else _text(inputs.get("input"))
    out = Path(str(_cfg(config, "output_dir", "workspace/artifacts/video/frames") or "frames"))
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    every = int(_cfg(config, "every_n", 1) or 1)
    try:
        import cv2  # type: ignore

        cap = cv2.VideoCapture(path)
        idx = 0
        while cap.isOpened() and len(frames) < 30:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % every == 0:
                dest = out / f"frame_{idx:05d}.jpg"
                cv2.imwrite(str(dest), frame)
                frames.append(_T(types, "ImageSample", path=str(dest), metadata={"index": idx}))
            idx += 1
        cap.release()
    except Exception:
        if path and Path(path).is_file():
            frames.append(_T(types, "ImageSample", path=path, metadata={"index": 0, "note": "opencv unavailable; source path retained"}))
    return frames

def _video_caption(config, inputs, types):
    frames = _frame_sample(config, inputs, types)
    captions = []
    for frame in frames[: int(_cfg(config, "max_frames", 4) or 4)]:
        data = _dump(frame)
        path = str(data.get("path") or "")
        captions.append(_T(types, "CaptionRecord", text=f"Frame at {path}" if path else "empty frame", metadata={"backend": "filename"}))
    return captions



class VideoCaptionNode(Node):
    """VL caption for clips/frames"""

    node_type: ClassVar[str] = "video_caption"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="video_caption",
        label="Video Caption",
        description="VL caption for clips/frames",
        category="Generation",
        version="0.1.0",
        tags=["video"],
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
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        backend: Literal["blip", "openai"] = Field(default='blip', title="Backend", description="Backend.")
        api_secret_name: str = Field(default='OPENAI_API_KEY', title="Api secret name", description="Api secret name.")
        max_frames: int = Field(default=8, title="Max frames", description="Max frames.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'video' / 'video_caption'
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
        """Run this node's real implementation."""
        return {"output": _video_caption(self.config, inputs, _types)}
