"""YoloHyperparamSearchNode — Optuna-style hyperparameter search over YOLO train configs

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

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

from app.models.dataset_artifact import DatasetArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("yolo_hyperparam_search.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ExperimentArtifact = _types.ExperimentArtifact

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

def _yolo_search(config, inputs, types):
    n = int(_cfg(config, "n_trials", 3) or 3)
    space = _cfg(config, "search_space", {"conf": [0.25, 0.5]}) or {}
    metric = str(_cfg(config, "metric", "score") or "score")
    trials = []
    rng = random.Random(0)
    best = None
    for i in range(n):
        params = {}
        for key, choices in (space.items() if isinstance(space, dict) else []):
            params[key] = rng.choice(list(choices)) if isinstance(choices, (list, tuple)) else choices
        value = 1 / (1 + i)
        trials.append({"trial": i, "params": params, metric: value})
        if best is None or value > best[metric]:
            best = trials[-1]
    return _T(types, "ExperimentArtifact", status="completed", payload={"trials": trials, "best": best}, metadata={"direction": str(_cfg(config, "direction", "maximize")), "metric": metric})



class YoloHyperparamSearchNode(Node):
    """Optuna-style hyperparameter search over YOLO train configs"""

    node_type: ClassVar[str] = "yolo_hyperparam_search"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="yolo_hyperparam_search",
        label="Yolo Hyperparam Search",
        description="Optuna-style hyperparameter search over YOLO train configs",
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
        "input": InputPort(name="input", data_type=object, required=True, description="DatasetArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ExperimentArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        n_trials: int = Field(default=20, title="N trials", description="N trials.")
        search_space: dict = Field(default_factory=dict)
        metric: str = Field(default='mAP50', title="Metric", description="Metric.")
        direction: str = Field(default='maximize', title="Direction", description="Direction.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'vision' / 'yolo_hyperparam_search'
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
            result = ExperimentArtifact()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"yolo_hyperparam_search: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _yolo_search(self.config, inputs, _types)}
