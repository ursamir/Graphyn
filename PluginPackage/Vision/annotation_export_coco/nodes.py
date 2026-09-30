"""AnnotationExportCocoNode — Export COCO JSON

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
        _types = importlib.import_module("annotation_export_coco.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

AnnotationExport = _types.AnnotationExport
ImageSample = _types.ImageSample
VisionDatasetArtifact = _types.VisionDatasetArtifact

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

def _out_path(config: Any, default_name: str) -> Path:
    raw = _cfg(config, "output_path") or _cfg(config, "output_dir") or _cfg(config, "persist_path")
    path = Path(str(raw or f"workspace/artifacts/proposed/{default_name}"))
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path

def _vision_images(obj: Any) -> list[dict]:
    out = []
    for item in _as_list(obj):
        data = _dump(item)
        if isinstance(data, str):
            data = {"path": data}
        if isinstance(data, dict):
            out.append(data)
    return out

def _export_labels(config, inputs, types, fmt: str):
    images = _vision_images(inputs.get("input"))
    dest = _out_path(config, fmt)
    folder = dest if dest.is_dir() else dest.parent
    folder.mkdir(parents=True, exist_ok=True)
    if fmt == "coco":
        coco = {"images": [], "annotations": [], "categories": []}
        for i, im in enumerate(images):
            coco["images"].append({"id": i, "file_name": str(im.get("path") or i)})
            for box in im.get("boxes") or []:
                coco["annotations"].append({"image_id": i, "bbox": box})
        path = folder / "annotations.json"
        path.write_text(json.dumps(coco), encoding="utf-8")
    else:
        path = folder / "labels"
        path.mkdir(exist_ok=True)
        for i, im in enumerate(images):
            lines = []
            for box in im.get("boxes") or []:
                data = box if isinstance(box, dict) else {"box": box}
                coords = data.get("box") or data
                if isinstance(coords, list):
                    lines.append("0 " + " ".join(str(float(c)) for c in coords[:4]))
            (path / f"{i}.txt").write_text("\n".join(lines), encoding="utf-8")
        if bool(_cfg(config, "create_data_yaml", True)):
            (folder / "data.yaml").write_text("path: .\ntrain: images\nval: images\nnames: [object]\n", encoding="utf-8")
        path = folder
    return _T(types, "AnnotationExport", path=str(path), format=fmt, metadata={"n": len(images)}) if hasattr(types, "AnnotationExport") else {"path": str(path), "format": fmt}

def _impl(config, inputs, types):
    return _export_labels(config, inputs, types, "coco")



class AnnotationExportCocoNode(Node):
    """Export COCO JSON"""

    node_type: ClassVar[str] = "annotation_export_coco"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="annotation_export_coco",
        label="Annotation Export Coco",
        description="Export COCO JSON",
        category="Output",
        version="0.1.0",
        tags=["vision"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[ImageSample] NEW|VisionDatasetArtifact NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="AnnotationExport NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        output_path: str = Field(default='workspace/datasets/vision/coco.json', title="Output path", description="Output path.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'annotation_export_coco'
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
            result = AnnotationExport()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"annotation_export_coco: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _impl(self.config, inputs, _types)}
