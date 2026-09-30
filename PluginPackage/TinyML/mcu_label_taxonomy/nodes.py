"""McuLabelTaxonomyNode — MCU class taxonomy remap

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
        _types = importlib.import_module("mcu_label_taxonomy.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

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

def _mcu_taxonomy(config, inputs, types):
    taxonomy = _cfg(config, "taxonomy", {}) or {}
    if isinstance(taxonomy, list):
        taxonomy = {str(i): name for i, name in enumerate(taxonomy)}
    drop = bool(_cfg(config, "drop_unknown", False))
    out = []
    for item in _as_list(inputs.get("input")):
        data = _dump(item)
        if not isinstance(data, dict):
            data = {"payload": item}
        label = str(data.get("label") or "")
        mapped = taxonomy.get(label, label)
        if drop and label not in taxonomy and mapped == label and taxonomy:
            continue
        out.append(_T(types, "McuSample", sample_id=str(data.get("sample_id") or ""), payload=data.get("payload"), modality=str(data.get("modality") or "audio"), label=str(mapped), metadata=data.get("metadata") or {}))
    return out



class McuLabelTaxonomyNode(Node):
    """MCU class taxonomy remap"""

    node_type: ClassVar[str] = "mcu_label_taxonomy"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="mcu_label_taxonomy",
        label="Mcu Label Taxonomy",
        description="MCU class taxonomy remap",
        category="Preprocessing",
        version="0.1.0",
        tags=["tinyml"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[McuSample] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[McuSample] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        taxonomy: dict = Field(default_factory=dict)
        drop_unknown: bool = Field(default=True, title="Drop unknown", description="Drop unknown.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'mcu_label_taxonomy'
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
            raise ImportError(f"mcu_label_taxonomy: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _mcu_taxonomy(self.config, inputs, _types)}
