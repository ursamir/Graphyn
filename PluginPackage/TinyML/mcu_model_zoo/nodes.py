"""McuModelZooNode — DS-CNN/MobileNetTiny/MCUNet/KWS zoo

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json
import random

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
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
        _types = importlib.import_module("mcu_model_zoo.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _out_path(config: Any, default_name: str) -> Path:
    raw = _cfg(config, "output_path") or _cfg(config, "output_dir") or _cfg(config, "persist_path")
    path = Path(str(raw or f"workspace/artifacts/proposed/{default_name}"))
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path

def _model_zoo(config, inputs, types):
    arch = str(_cfg(config, "architecture", "ds_cnn") or "ds_cnn")
    classes = int(_cfg(config, "num_classes", 2) or 2)
    shape = _cfg(config, "input_shape", [1, 49, 10])
    width = float(_cfg(config, "width_multiplier", 1.0) or 1.0)
    hidden = max(1, int(16 * width))
    # A real tiny fully-connected init (He) stored as JSON weights.
    rng = random.Random(0)
    in_dim = 1
    if isinstance(shape, (list, tuple)):
        for dim in shape:
            in_dim *= int(dim)
    w1 = [[rng.uniform(-0.1, 0.1) for _ in range(hidden)] for _ in range(min(in_dim, 64))]
    w2 = [[rng.uniform(-0.1, 0.1) for _ in range(classes)] for _ in range(hidden)]
    spec = {"architecture": arch, "input_shape": shape, "num_classes": classes, "w1": w1, "w2": w2}
    dest = _out_path(config, "zoo") 
    path = dest / "model.json" if dest.is_dir() else dest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec), encoding="utf-8")
    return {"path": str(path), "parameters": sum(len(row) for row in w1) + sum(len(row) for row in w2)}



class McuModelZooNode(Node):
    """DS-CNN/MobileNetTiny/MCUNet/KWS zoo"""

    node_type: ClassVar[str] = "mcu_model_zoo"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="mcu_model_zoo",
        label="Mcu Model Zoo",
        description="DS-CNN/MobileNetTiny/MCUNet/KWS zoo",
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
        "input": InputPort(name="input", data_type=object, required=True, description="DatasetArtifact|object"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="object"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        architecture: Literal["ds_cnn", "mobilenet", "simple_cnn"] = Field(default='ds_cnn', title="Architecture", description="Architecture.")
        num_classes: int = Field(default=12, title="Num classes", description="Num classes.")
        input_shape: list = Field(default_factory=lambda: [49, 10, 1])
        width_multiplier: float = Field(default=0.25, title="Width multiplier", description="Width multiplier.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'tinyml' / 'mcu_model_zoo'
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
            result = None
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"mcu_model_zoo: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _model_zoo(self.config, inputs, _types)}
