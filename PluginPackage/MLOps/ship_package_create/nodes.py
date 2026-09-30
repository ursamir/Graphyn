"""ShipPackageCreateNode — Create ship package (REST semantics)

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

from app.models.deployment_artifact import DeploymentArtifact

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("ship_package_create.types")
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

def _pick(config: Any, name: str, deployment: dict, default: str) -> str:
    """Non-empty config wins; else the input's value (top-level or metadata); else default."""
    val = _cfg(config, name, None)
    if isinstance(val, str) and val.strip():
        return val.strip()
    meta = deployment.get("metadata") if isinstance(deployment.get("metadata"), dict) else {}
    for src in (deployment, meta):
        v = src.get(name)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


def _as_target(val: Any) -> dict | None:
    if isinstance(val, dict):
        return dict(val) if val else None
    if isinstance(val, str) and val.strip():
        return {"runtime": val.strip(), "arch": "cpu"}
    return None


def _ship_create(config, inputs, types):
    from app.core.mlops.ship_packages import create_package

    deployment = _dump(inputs.get("deployment")) or {}
    if not isinstance(deployment, dict):
        deployment = {}
    meta = deployment.get("metadata") if isinstance(deployment.get("metadata"), dict) else {}
    target = (
        _as_target(_cfg(config, "target", None))
        or _as_target(deployment.get("target"))
        or _as_target(meta.get("target"))
    )
    if target is None and deployment.get("model_format"):
        target = {"runtime": str(deployment["model_format"]), "arch": str(deployment.get("target_hardware") or "cpu")}
    if target is None:
        target = {"runtime": "python", "arch": "cpu"}
    record = create_package(
        _project_dir(),
        project_name=_pick(config, "project", deployment, "default"),
        model_name=_pick(config, "model_name", deployment, "model"),
        model_stage_or_version=_pick(config, "model_stage_or_version", deployment, "latest"),
        target=target,
        env=str(_cfg(config, "env", "draft") or "draft"),
        unsigned_allowed=bool(_cfg(config, "unsigned_allowed", True)),
    )
    return _ship_ref(types, record if isinstance(record, dict) else {"status": "built"})



class ShipPackageCreateNode(Node):
    """Create ship package (REST semantics)"""

    node_type: ClassVar[str] = "ship_package_create"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="ship_package_create",
        label="Ship Package Create",
        description="Create ship package (REST semantics)",
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
        "deployment": InputPort(name="deployment", data_type=object | None, required=False, description="DeploymentArtifact optional"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ShipPackageRef NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        project: str = Field(default='', title="Project", description="Empty: use the input's project, else 'default'.")
        model_name: str = Field(default='', title="Model name", description="Empty: use the input's model_name, else 'model'.")
        model_stage_or_version: str = Field(default='', title="Model stage or version", description="Empty: use the input's value, else 'latest'.")
        target: dict = Field(default_factory=dict, title="Target", description="Target object (runtime/arch/...). Empty: use the input's target, else python/cpu.")
        env: str = Field(default='draft', title="Env", description="Env.")
        unsigned_allowed: bool = Field(default=True, title="Unsigned allowed", description="Unsigned allowed.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'ship_package_create'
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
            raise ImportError(f"ship_package_create: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _ship_create(self.config, inputs, _types)}
