"""CanaryGateNode — Canary promote/hold gate

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import importlib
import logging
import math
from pathlib import Path
from typing import ClassVar, Any, Optional
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
        _types = importlib.import_module("canary_gate.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

CanaryDecision = _types.CanaryDecision

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

def _metrics_dict(obj: Any) -> dict:
    """Return the metric mapping carried by a dict / ModelArtifact / nested dict."""
    if obj is None:
        return {}
    metrics_attr = getattr(obj, "metrics", None)
    if isinstance(metrics_attr, dict):
        return dict(metrics_attr)
    data = _dump(obj)
    if isinstance(data, dict):
        nested = data.get("metrics")
        if isinstance(nested, dict):
            # ModelArtifact-like dict: nested metrics win, top-level scalars kept as fallback keys.
            merged = {k: v for k, v in data.items() if k != "metrics"}
            merged.update(nested)
            return merged
        return dict(data)
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        return {"value": data}
    raise TypeError(f"canary_gate: unsupported metrics input type {type(obj).__name__}")


def _lookup(metrics: dict, key: str) -> Any:
    if key in metrics:
        return metrics[key]
    cur: Any = metrics
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            import numpy as np  # type: ignore

            if isinstance(value, np.generic) and np.issubdtype(type(value), np.number):
                value = float(value)
            else:
                return None
        except ImportError:
            return None
    value = float(value)
    return value if math.isfinite(value) else None


def _canary(config, inputs, types):
    key = str(_cfg(config, "metric_key", "test_accuracy") or "").strip()
    if not key:
        raise ValueError("canary_gate: metric_key must be set")
    higher = bool(_cfg(config, "higher_is_better", True))
    min_value = _cfg(config, "min_value", None)
    max_value = _cfg(config, "max_value", None)
    max_reg = _cfg(config, "max_regression", None)

    metrics = _metrics_dict(inputs.get("metrics"))
    raw = _lookup(metrics, key)
    value = _finite(raw)
    out_metrics: dict[str, Any] = {key: value if value is not None else raw}

    baseline_value: float | None = None
    baseline_in = inputs.get("baseline")
    if baseline_in is not None:
        braw = _lookup(_metrics_dict(baseline_in), key)
        baseline_value = _finite(braw)
        if baseline_value is None:
            return _T(types, "CanaryDecision", promote=False,
                      reason=f"baseline metric {key} missing or non-finite ({braw!r})",
                      metrics={**out_metrics, "baseline": braw})
    elif _cfg(config, "baseline_value", None) is not None:
        baseline_value = _finite(_cfg(config, "baseline_value", None))
        if baseline_value is None:
            raise ValueError("canary_gate: config.baseline_value must be a finite number")

    if raw is None:
        return _T(types, "CanaryDecision", promote=False, reason=f"metric {key} missing", metrics=out_metrics)
    if value is None:
        return _T(types, "CanaryDecision", promote=False,
                  reason=f"metric {key}={raw!r} is not a finite number", metrics=out_metrics)
    if min_value is not None and value < float(min_value):
        return _T(types, "CanaryDecision", promote=False, reason=f"{key}={value} < min {min_value}", metrics=out_metrics)
    if max_value is not None and value > float(max_value):
        return _T(types, "CanaryDecision", promote=False, reason=f"{key}={value} > max {max_value}", metrics=out_metrics)
    if baseline_value is not None:
        regression = (baseline_value - value) if higher else (value - baseline_value)
        out_metrics.update({"baseline": baseline_value, "regression": regression})
        if max_reg is not None and regression > float(max_reg):
            return _T(types, "CanaryDecision", promote=False,
                      reason=f"{key} regressed by {regression:.6g} vs baseline {baseline_value} (max {max_reg})",
                      metrics=out_metrics)
    return _T(types, "CanaryDecision", promote=True, reason="all gates passed", metrics=out_metrics)



class CanaryGateNode(Node):
    """Canary promote/hold gate"""

    node_type: ClassVar[str] = "canary_gate"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="canary_gate",
        label="Canary Gate",
        description="Canary promote/hold gate",
        category="Quality",
        version="0.1.0",
        tags=["mlops"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "metrics": InputPort(name="metrics", data_type=object, required=True, description="dict|ModelArtifact"),
        "baseline": InputPort(name="baseline", data_type=object | None, required=False, description="dict|ModelArtifact baseline (optional)"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="CanaryDecision NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        metric_key: str = Field(default='test_accuracy', title="Metric key", description="Metric key.")
        min_value: Optional[float] = Field(default=0.0, title="Min value", description="Hold when metric < min_value (None disables).")
        max_value: Optional[float] = Field(default=None, title="Max value", description="Hold when metric > max_value (None disables).")
        max_regression: Optional[float] = Field(default=0.02, title="Max regression", description="Hold when metric regresses more than this vs baseline (baseline port or baseline_value).")
        baseline_value: Optional[float] = Field(default=None, title="Baseline value", description="Baseline metric when no baseline input is wired.")
        higher_is_better: bool = Field(default=True, title="Higher is better", description="Direction of the metric (False for loss-like metrics).")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'canary_gate'
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
            result = CanaryDecision()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"canary_gate: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _canary(self.config, inputs, _types)}
