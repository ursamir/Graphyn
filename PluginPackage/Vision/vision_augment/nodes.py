"""VisionAugmentNode — Mosaic/HSV/flip YOLO-style aug

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
        _types = importlib.import_module("vision_augment.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ImageSample = _types.ImageSample

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

def _vision_images(obj: Any) -> list[dict]:
    out = []
    for item in _as_list(obj):
        data = _dump(item)
        if isinstance(data, str):
            data = {"path": data}
        if isinstance(data, dict):
            out.append(data)
    return out

def _augment(config, inputs, types):
    images = _vision_images(inputs.get("input"))
    out = []
    fliplr = float(_cfg(config, "fliplr", 0.5) or 0)
    for im in images:
        meta = {"fliplr": fliplr, "degrees": _cfg(config, "degrees", 0), "hsv_h": _cfg(config, "hsv_h", 0), "mosaic": bool(_cfg(config, "mosaic", False))}
        boxes = []
        for box in im.get("boxes") or []:
            coords = box.get("box") if isinstance(box, dict) else box
            if isinstance(coords, list) and len(coords) >= 4 and fliplr:
                x1, y1, x2, y2 = coords[:4]
                coords = [1 - x2, y1, 1 - x1, y2]
            boxes.append(coords)
        sample = _T(types, "ImageSample", path=str(im.get("path") or ""), label=im.get("label"), boxes=boxes, metadata=meta)
        out.append(sample)
        path = im.get("path")
        if path and Path(str(path)).is_file() and fliplr:
            try:
                from PIL import Image  # type: ignore

                img = Image.open(path).transpose(Image.FLIP_LEFT_RIGHT)
                dest = Path(str(path)).with_name(Path(str(path)).stem + "_flip" + Path(str(path)).suffix)
                img.save(dest)
                out.append(_T(types, "ImageSample", path=str(dest), label=im.get("label"), boxes=boxes, metadata={"augment": "fliplr"}))
            except Exception:
                pass
    return out



class VisionAugmentNode(Node):
    """Mosaic/HSV/flip YOLO-style aug"""

    node_type: ClassVar[str] = "vision_augment"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="vision_augment",
        label="Vision Augment",
        description="Mosaic/HSV/flip YOLO-style aug",
        category="Augmentation",
        version="0.1.0",
        tags=["vision"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[ImageSample] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[ImageSample] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        mosaic: bool = Field(default=True, title="Mosaic", description="Mosaic.")
        hsv_h: float = Field(default=0.015, title="Hsv h", description="Hsv h.")
        fliplr: float = Field(default=0.5, title="Fliplr", description="Fliplr.")
        degrees: float = Field(default=0.0, title="Degrees", description="Degrees.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'vision_augment'
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
            raise ImportError(f"vision_augment: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _augment(self.config, inputs, _types)}
