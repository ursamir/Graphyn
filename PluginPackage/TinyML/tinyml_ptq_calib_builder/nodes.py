"""TinymlPtqCalibBuilderNode — Build PTQ representative set

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
        _types = importlib.import_module("tinyml_ptq_calib_builder.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _as_list(obj: Any) -> list:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, tuple):
        return list(obj)
    return [obj]

def _calib(config, inputs, types):
    items = _as_list(inputs.get("input"))
    max_n = int(_cfg(config, "max_samples", 64) or 64)
    seed = int(_cfg(config, "seed", 0) or 0)
    rng = random.Random(seed)
    chosen = items
    if len(items) > max_n:
        chosen = rng.sample(items, max_n)
    return {"samples": chosen, "n": len(chosen), "stratify": bool(_cfg(config, "stratify", False))}



class TinymlPtqCalibBuilderNode(Node):
    """Build PTQ representative set"""

    node_type: ClassVar[str] = "tinyml_ptq_calib_builder"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="tinyml_ptq_calib_builder",
        label="Tinyml Ptq Calib Builder",
        description="Build PTQ representative set",
        category="ML",
        version="0.1.0",
        tags=["tinyml"],
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
        "output": OutputPort(name="output", data_type=object, description="DatasetArtifact"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        max_samples: int = Field(default=100, title="Max samples", description="Max samples.")
        stratify: bool = Field(default=True, title="Stratify", description="Stratify.")
        seed: int = Field(default=42, title="Seed", description="Seed.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'tinyml_ptq_calib_builder'
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
            raise ImportError(f"tinyml_ptq_calib_builder: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _calib(self.config, inputs, _types)}
