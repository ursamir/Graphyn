"""AbAssignNode — Deterministic A/B assignment

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import hashlib

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
        _types = importlib.import_module("ab_assign.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

AbAssignment = _types.AbAssignment

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

def _unit_id(obj: Any, field: str) -> str:
    if obj is None:
        raise ValueError("ab_assign: input unit is required")
    if isinstance(obj, bool):
        raise TypeError("ab_assign: boolean is not a valid unit id")
    if isinstance(obj, (str, int)):
        uid = str(obj).strip()
        if not uid:
            raise ValueError("ab_assign: unit id is empty")
        return uid
    if isinstance(obj, (list, tuple, set)):
        raise TypeError("ab_assign: expected a single unit (str/int/record), got a collection")
    data = _dump(obj)
    if isinstance(data, dict):
        if not field:
            raise ValueError("ab_assign: record input requires config.unit_id_field")
        val = data.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            raise ValueError(f"ab_assign: unit record lacks {field!r} (keys: {sorted(data)[:20]})")
        return str(val).strip()
    raise TypeError(f"ab_assign: unsupported unit type {type(obj).__name__}")


def _ab_assign(config, inputs, types):
    key = str(_cfg(config, "experiment_key", "default") or "default")
    variants_raw = _cfg(config, "variants", None)
    variants = [str(v) for v in (["control", "treatment"] if variants_raw is None else variants_raw)]
    if not variants:
        raise ValueError("ab_assign: variants must be non-empty")
    if len(set(variants)) != len(variants):
        raise ValueError(f"ab_assign: duplicate variants {variants}")
    weights_raw = _cfg(config, "weights", None)
    weights = [float(w) for w in (weights_raw or [])]
    if not weights:
        weights = [1.0] * len(variants)
    if len(weights) != len(variants):
        raise ValueError(f"ab_assign: {len(weights)} weights for {len(variants)} variants")
    if any(w < 0 or w != w for w in weights):
        raise ValueError(f"ab_assign: weights must be non-negative numbers, got {weights}")
    total = sum(weights)
    if total <= 0:
        raise ValueError("ab_assign: weights must sum to > 0")

    field = str(_cfg(config, "unit_id_field", "unit_id") or "")
    subject = _unit_id(inputs.get("input"), field)
    digest = hashlib.sha256(f"{key}:{subject}".encode("utf-8")).hexdigest()
    bucket = int(digest[:15], 16) / float(16 ** 15)  # uniform in [0, 1)
    cursor = 0.0
    chosen = next(v for v, w in zip(reversed(variants), reversed(weights)) if w > 0)
    for variant, weight in zip(variants, weights):
        cursor += weight / total
        if weight > 0 and bucket < cursor:
            chosen = variant
            break
    return _T(types, "AbAssignment", variant=chosen, unit_id=subject)



class AbAssignNode(Node):
    """Deterministic A/B assignment"""

    node_type: ClassVar[str] = "ab_assign"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="ab_assign",
        label="Ab Assign",
        description="Deterministic A/B assignment",
        category="MLOps",
        version="0.1.0",
        tags=["mlops"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="Any"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="AbAssignment NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        experiment_key: str = Field(default='default', title="Experiment key", description="Experiment key.")
        variants: list[str] = Field(default_factory=lambda: ["control", "treatment"], title="Variants", description="Variant names (unique, non-empty).")
        weights: list[float] = Field(default_factory=lambda: [0.5, 0.5], title="Weights", description="Non-negative weights, one per variant (empty = uniform).")
        unit_id_field: str = Field(default="unit_id", title="Unit id field", description="Field holding the unit id when the input is a record; missing field is an error.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'ab_assign'
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
            result = AbAssignment()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"ab_assign: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _ab_assign(self.config, inputs, _types)}
