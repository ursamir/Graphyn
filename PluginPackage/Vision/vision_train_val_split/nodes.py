"""VisionTrainValSplitNode — Vision stratified splits

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json
import random

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
        _types = importlib.import_module("vision_train_val_split.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

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

def _vision_split(config, inputs, types):
    images = _vision_images(inputs.get("input"))
    ratios = _cfg(config, "split_ratios", {"train": 0.8, "val": 0.2}) or {"train": 0.8, "val": 0.2}
    if isinstance(ratios, str):
        ratios = json.loads(ratios)
    rng = random.Random(int(_cfg(config, "seed", 0) or 0))
    order = images[:]
    rng.shuffle(order)
    n = len(order)
    cursor = 0
    splits = {}
    names = list(ratios)
    for i, name in enumerate(names):
        if i == len(names) - 1:
            count = n - cursor
        else:
            count = int(n * float(ratios[name]))
        splits[name] = order[cursor : cursor + count]
        cursor += count
    dest = _out_path(config, "splits")
    folder = dest if dest.is_dir() else dest.parent
    folder.mkdir(parents=True, exist_ok=True)
    yaml_path = folder / "split.json"
    yaml_path.write_text(json.dumps({k: [im.get("path") for im in v] for k, v in splits.items()}), encoding="utf-8")
    return _T(types, "VisionDatasetArtifact", root=str(folder), task="detect", names=sorted({str(im.get("label") or "") for im in images}), yaml_path=str(yaml_path), metadata={"n": n, "counts": {k: len(v) for k, v in splits.items()}})



class VisionTrainValSplitNode(Node):
    """Vision stratified splits"""

    node_type: ClassVar[str] = "vision_train_val_split"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="vision_train_val_split",
        label="Vision Train Val Split",
        description="Vision stratified splits",
        category="ML",
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
        "output": OutputPort(name="output", data_type=object, description="VisionDatasetArtifact NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        split_ratios: dict = Field(default_factory=dict)
        seed: int = Field(default=42, title="Seed", description="Seed.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'vision_train_val_split'
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
            result = DatasetArtifact(labels=[], input_shape=(), n_classes=0, metadata={"stub": True})
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"vision_train_val_split: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _vision_split(self.config, inputs, _types)}
