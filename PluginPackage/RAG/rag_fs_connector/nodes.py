"""RagFsConnectorNode — Filesystem docs connector

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json

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
        _types = importlib.import_module("rag_fs_connector.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

RawDocument = _types.RawDocument

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

def _fs_connector(config, inputs, types):
    root = Path(str(_cfg(config, "path", ".") or "."))
    recursive = bool(_cfg(config, "recursive", True))
    exts = _cfg(config, "extensions", [".txt", ".md", ".json"]) or [".txt", ".md"]
    exts = {str(e).lower() if str(e).startswith(".") else f".{e}" for e in exts}
    files = root.rglob("*") if recursive else root.glob("*")
    docs = []
    if root.is_file():
        files = [root]
    for path in files:
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        docs.append(_T(types, "RawDocument", path=str(path), text=text, metadata={"bytes": path.stat().st_size}))
    return docs



class RagFsConnectorNode(Node):
    """Filesystem docs connector"""

    node_type: ClassVar[str] = "rag_fs_connector"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="rag_fs_connector",
        label="Rag Fs Connector",
        description="Filesystem docs connector",
        category="Input",
        version="0.1.0",
        tags=["rag"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {}

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[RawDocument] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        path: str = Field(default='', title="Path", description="Path.")
        recursive: bool = Field(default=True, title="Recursive", description="Recursive.")
        extensions: list = Field(default_factory=list)

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'rag' / 'rag_fs_connector'
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
            raise ImportError(f"rag_fs_connector: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _fs_connector(self.config, inputs, _types)}
