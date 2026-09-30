"""ShipPackagePromoteNode — Promote draft→staging→prod

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
        _types = importlib.import_module("ship_package_promote.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ShipPackageRef = _types.ShipPackageRef

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

def _project_dir() -> Path:
    from app.core.config import project_dir

    return project_dir()

def _ship_ref(types, record: dict) -> Any:
    return _T(
        types,
        "ShipPackageRef",
        package_id=str(record.get("package_id") or record.get("id") or ""),
        path=str(record.get("path") or record.get("dir") or ""),
        state=str(record.get("status") or record.get("state") or ""),
        metadata=record,
    )

def _ship_promote(config, inputs, types):
    from app.core.mlops.ship_packages import promote_package

    pkg = _dump(inputs.get("package")) or {}
    package_id = str(pkg.get("package_id") or pkg.get("id") or "")
    record = promote_package(
        _project_dir(),
        package_id,
        to_env=str(_cfg(config, "to_env", "staging") or "staging"),
        approve=bool(_cfg(config, "approve", False)),
    )
    return _ship_ref(types, record if isinstance(record, dict) else {})



class ShipPackagePromoteNode(Node):
    """Promote draft→staging→prod"""

    node_type: ClassVar[str] = "ship_package_promote"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="ship_package_promote",
        label="Ship Package Promote",
        description="Promote draft→staging→prod",
        category="Ship",
        version="0.1.0",
        tags=["mlops"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "package": InputPort(name="package", data_type=object, required=True, description="ShipPackageRef NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ShipPackageRef NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        to_env: str = Field(default='staging', title="To env", description="To env.")
        approve: bool = Field(default=False, title="Approve", description="Approve.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'ship_package_promote'
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
            result = ShipPackageRef()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"ship_package_promote: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _ship_promote(self.config, inputs, _types)}
