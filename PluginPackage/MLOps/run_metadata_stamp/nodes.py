"""RunMetadataStampNode — Stamp git/versions/seed metadata

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
        _types = importlib.import_module("run_metadata_stamp.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj

def _run_stamp(config, inputs, types):
    payload = _dump(inputs.get("input"))
    stamp = {
        "input": payload,
        "seed": _cfg(config, "seed", None),
    }
    if bool(_cfg(config, "include_git", True)):
        try:
            import subprocess

            rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
            stamp["git_sha"] = rev.stdout.strip() if rev.returncode == 0 else None
        except Exception:
            stamp["git_sha"] = None
    return stamp



class RunMetadataStampNode(Node):
    """Stamp git/versions/seed metadata"""

    node_type: ClassVar[str] = "run_metadata_stamp"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="run_metadata_stamp",
        label="Run Metadata Stamp",
        description="Stamp git/versions/seed metadata",
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
        "output": OutputPort(name="output", data_type=object, description="Any"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        include_git: bool = Field(default=True, title="Include git", description="Include git.")
        seed: int = Field(default=0, title="Seed", description="Seed.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'mlops' / 'run_metadata_stamp'
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
            raise ImportError(f"run_metadata_stamp: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _run_stamp(self.config, inputs, _types)}
