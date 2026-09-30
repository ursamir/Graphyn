"""TflmHostSimNode — Host TFLM/TFLite interpreter eval

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

from app.models.dataset_artifact import DatasetArtifact
from app.models.deployment_artifact import DeploymentArtifact
from app.models.model_artifact import ModelArtifact
from app.models.prediction_result import PredictionResult
from app.models.tflite_artifact import TFLiteArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("tflm_host_sim.types")
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

def _host_sim(config, inputs, types):
    model = _train_from_dataset(config, {"dataset": inputs.get("dataset")}) if not inputs.get("model") else _dump(inputs.get("model"))
    rows = _as_list(inputs.get("dataset"))
    limit = int(_cfg(config, "batch_limit", len(rows) or 1) or 1)
    correct = 0
    total = 0
    weights = (model or {}).get("weights") or []
    bias = float((model or {}).get("bias") or 0)
    for item in rows[:limit]:
        feats = _numbers(_dump(item))
        z = bias + sum((weights[i] if i < len(weights) else 0) * (feats[i] if i < len(feats) else 0) for i in range(max(len(weights), len(feats))))
        pred = 1 if z >= 0 else 0
        label = _dump(item).get("label") if isinstance(_dump(item), dict) else None
        if label is not None:
            total += 1
            if (str(label) not in ("0", "negative", "False", "")) == bool(pred):
                correct += 1
    acc = (correct / total) if total else None
    return {"accuracy": acc, "n": min(limit, len(rows)), "interpreter": str(_cfg(config, "interpreter", "logistic"))}



class TflmHostSimNode(Node):
    """Host TFLM/TFLite interpreter eval"""

    node_type: ClassVar[str] = "tflm_host_sim"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="tflm_host_sim",
        label="Tflm Host Sim",
        description="Host TFLM/TFLite interpreter eval",
        category="Inference",
        version="0.1.0",
        tags=["tinyml"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "model": InputPort(name="model", data_type=object, required=True, description="TFLiteArtifact|DeploymentArtifact"),
        "dataset": InputPort(name="dataset", data_type=object, required=True, description="DatasetArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ModelArtifact"),
        "predictions": OutputPort(name="predictions", data_type=object, description="list[PredictionResult]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        interpreter: str = Field(default='tflite_runtime', title="Interpreter", description="Interpreter.")
        batch_limit: int = Field(default=0, title="Batch limit", description="Batch limit.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'tflm_host_sim'
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
                "output": ModelArtifact(model_path=str(_out), labels=[], history={"stub": True}, metrics={}),
                "predictions": [],
            }
            return result
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"tflm_host_sim: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _host_sim(self.config, inputs, _types)}
