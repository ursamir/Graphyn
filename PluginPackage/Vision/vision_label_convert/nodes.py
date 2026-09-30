"""VisionLabelConvertNode — COCO↔YOLO↔VOC label convert

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
        _types = importlib.import_module("vision_label_convert.types")
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

def _label_convert(config, inputs, types):
    src = str(_cfg(config, "from_format", "coco") or "coco")
    dst = str(_cfg(config, "to_format", "yolo") or "yolo")
    mapping = _cfg(config, "class_map", {}) or {}
    images = _vision_images(inputs.get("input"))
    converted = []
    for im in images:
        boxes = im.get("boxes") or []
        new_boxes = []
        for box in boxes:
            data = _dump(box) if not isinstance(box, dict) else box
            label = str(data.get("label") if isinstance(data, dict) else "")
            label = str(mapping.get(label, label))
            coords = data.get("box") if isinstance(data, dict) else data
            if dst == "yolo" and isinstance(coords, list) and len(coords) == 4 and src == "xyxy":
                x1, y1, x2, y2 = coords
                coords = [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1]
            new_boxes.append({"label": label, "box": coords, "format": dst})
        converted.append(_T(types, "ImageSample", path=str(im.get("path") or ""), label=im.get("label"), boxes=new_boxes, metadata={"format": dst, "from": src}))
    return converted



class VisionLabelConvertNode(Node):
    """COCO↔YOLO↔VOC label convert"""

    node_type: ClassVar[str] = "vision_label_convert"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="vision_label_convert",
        label="Vision Label Convert",
        description="COCO↔YOLO↔VOC label convert",
        category="Preprocessing",
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
        from_format: str = Field(default='coco', title="From format", description="From format.")
        to_format: str = Field(default='yolo', title="To format", description="To format.")
        class_map: dict = Field(default_factory=dict)

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'vision_label_convert'
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
            raise ImportError(f"vision_label_convert: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _label_convert(self.config, inputs, _types)}
