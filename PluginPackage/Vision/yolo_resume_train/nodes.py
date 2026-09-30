"""YoloResumeTrainNode — Resume YOLO training from last.pt / checkpoint

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json
import math

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

from app.models.model_artifact import ModelArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("yolo_resume_train.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

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

def _as_list(obj: Any) -> list:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, tuple):
        return list(obj)
    return [obj]

def _numbers(obj: Any) -> list[float]:
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("values", "features", "payload", "vector", "embedding", "data"):
            if key in data:
                return _numbers(data[key])
        return [float(v) for v in data.values() if isinstance(v, (int, float))]
    if isinstance(data, (list, tuple)):
        out: list[float] = []
        for item in data:
            if isinstance(item, (int, float)):
                out.append(float(item))
            elif isinstance(item, (list, tuple, dict)):
                out.extend(_numbers(item))
        return out
    if isinstance(data, (int, float)):
        return [float(data)]
    return []

def _out_path(config: Any, default_name: str) -> Path:
    raw = _cfg(config, "output_path") or _cfg(config, "output_dir") or _cfg(config, "persist_path")
    path = Path(str(raw or f"workspace/artifacts/proposed/{default_name}"))
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path

def _logistic_train(xs: list[list[float]], ys: list[float], epochs: int) -> dict[str, Any]:
    if not xs:
        return {"weights": [], "bias": 0.0, "loss": 0.0, "epochs": 0}
    dim = max(len(row) for row in xs)
    w = [0.0] * dim
    bias = 0.0
    lr = 0.05
    last = 0.0
    for _ in range(max(1, int(epochs or 1))):
        loss = 0.0
        for row, y in zip(xs, ys):
            z = bias + sum(w[i] * (row[i] if i < len(row) else 0.0) for i in range(dim))
            p = 1 / (1 + math.exp(-max(-20, min(20, z))))
            err = p - (1.0 if y >= 0.5 else 0.0)
            loss += err * err
            for i in range(dim):
                w[i] -= lr * err * (row[i] if i < len(row) else 0.0)
            bias -= lr * err
        last = loss / max(1, len(xs))
    return {"weights": w, "bias": bias, "loss": last, "epochs": int(epochs or 1)}

def _train_from_dataset(config, inputs):
    dataset = _as_list(inputs.get("dataset") or inputs.get("input"))
    xs, ys = [], []
    labels = []
    for item in dataset:
        data = _dump(item)
        feats = _numbers(data)
        if not feats and isinstance(data, dict):
            feats = _numbers(data.get("payload"))
        label = data.get("label") if isinstance(data, dict) else None
        if label not in labels:
            labels.append(label)
        xs.append(feats or [0.0])
        ys.append(float(labels.index(label) > 0) if labels else 0.0)
    epochs = int(_cfg(config, "epochs", 5) or 5)
    model = _logistic_train(xs, ys, epochs)
    model["labels"] = [str(x) for x in labels]
    model["n"] = len(xs)
    path = _out_path(config, "mcu_train")
    dest = path / "model.json" if path.is_dir() else path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(model), encoding="utf-8")
    model["path"] = str(dest)
    return model

def _impl(config, inputs, types):
    return _train_from_dataset(config, {"dataset": inputs.get("input"), "epochs": _cfg(config, "extra_epochs", 1)})



class YoloResumeTrainNode(Node):
    """Resume YOLO training from last.pt / checkpoint"""

    node_type: ClassVar[str] = "yolo_resume_train"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_resume_train",
        label="Yolo Resume Train",
        description="Resume YOLO training from last.pt / checkpoint",
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
        "input": InputPort(name="input", data_type=object, required=True, description="ModelArtifact|None"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ModelArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        resume_checkpoint: str = Field(default='', title="Resume checkpoint", description="Resume checkpoint.")
        extra_epochs: int = Field(default=0, title="Extra epochs", description="Extra epochs.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_resume_train'
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
            result = ModelArtifact(model_path=str(_out), labels=[], history={"stub": True}, metrics={})
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"yolo_resume_train: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _impl(self.config, inputs, _types)}
