"""FeatureStoreReadNode — Light feature store read

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=True returns typed minimal outputs without heavy deps.
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

from app.models.feature_array import FeatureArray

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("feature_store_read.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

FeatureStoreRef = _types.FeatureStoreRef

log = logging.getLogger(__name__)


class FeatureStoreReadNode(Node):
    """Light feature store read"""

    node_type: ClassVar[str] = "feature_store_read"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="feature_store_read",
        label="Feature Store Read",
        description="Light feature store read",
        category="MLOps",
        version="0.1.0",
        tags=["mlops", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "store": InputPort(name="store", data_type=object, required=True, description="FeatureStoreRef NEW"),
        "keys": InputPort(name="keys", data_type=object, required=True, description="list[str]"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[FeatureArray]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        persist_path: str = Field(default='workspace/artifacts/feature_store', title="Persist path", description="Persist path.")
        as_of: str = Field(default='', title="As of", description="As of.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'feature_store_read'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = []
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"feature_store_read: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

    def _process_real(self, inputs: dict):
        """Override point for richer backends; default = stub path."""
        # Keep default identical to stub so unit tests stay offline.
        prev = self.config.stub
        object.__setattr__(self.config, 'stub', True) if hasattr(self.config, 'model_copy') else None
        try:
            self.config.stub = True  # type: ignore[misc]
        except Exception:
            pass
        try:
            # Re-enter stub branch
            out_dir = Path('workspace/artifacts') / 'mlops' / 'feature_store_read'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": []}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
