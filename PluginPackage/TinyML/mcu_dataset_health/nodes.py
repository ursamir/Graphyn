"""McuDatasetHealthNode — MCU dataset class balance health

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations
from collections import Counter

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
        _types = importlib.import_module("mcu_dataset_health.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DatasetHealthReport = _types.DatasetHealthReport
McuSample = _types.McuSample

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

def _mcu_health(config, inputs, types):
    items = _as_list(inputs.get("input"))
    labels = []
    for item in items:
        data = _dump(item)
        if isinstance(data, dict):
            labels.append(str(data.get("label") or "unknown"))
    counts = Counter(labels)
    min_per = int(_cfg(config, "min_per_class", 1) or 1)
    ratio = float(_cfg(config, "max_imbalance_ratio", 10) or 10)
    under = [k for k, v in counts.items() if v < min_per]
    vals = list(counts.values()) or [1]
    imbalance = (max(vals) / min(vals)) if min(vals) else 0
    ok = not under and imbalance <= ratio
    issues = [f"under-min:{k}" for k in under]
    if imbalance > ratio:
        issues.append(f"imbalance:{imbalance:.2f}")
    return _T(
        types,
        "DatasetHealthReport",
        ok=not issues,
        issues=issues,
        stats={"counts": dict(counts), "imbalance": imbalance, "n": len(items)},
    )



class McuDatasetHealthNode(Node):
    """MCU dataset class balance health"""

    node_type: ClassVar[str] = "mcu_dataset_health"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="mcu_dataset_health",
        label="Mcu Dataset Health",
        description="MCU dataset class balance health",
        category="Quality",
        version="0.1.0",
        tags=["tinyml"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[McuSample] NEW|DatasetArtifact"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="DatasetHealthReport NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        min_per_class: int = Field(default=50, title="Min per class", description="Min per class.")
        max_imbalance_ratio: float = Field(default=5.0, title="Max imbalance ratio", description="Max imbalance ratio.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'mcu_dataset_health'
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
            result = DatasetHealthReport()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"mcu_dataset_health: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _mcu_health(self.config, inputs, _types)}
