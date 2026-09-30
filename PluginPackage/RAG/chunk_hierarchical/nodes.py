"""ChunkHierarchicalNode — Parent/child hierarchical chunks

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import hashlib
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
        _types = importlib.import_module("chunk_hierarchical.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Chunk = _types.Chunk
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

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj

def _text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list):
        return "\n".join(_text(x) for x in obj)
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("text", "query", "content", "answer", "user", "path", "value", "final"):
            if data.get(key):
                return str(data[key])
        return json.dumps(data, default=str)
    return str(obj)

def _chunk_id(text: str, index: int) -> str:
    digest = hashlib.sha1(f"{index}:{text}".encode()).hexdigest()[:12]
    return f"c{index}-{digest}"

def _split_chunks(text: str, size: int, overlap: int) -> list[str]:
    size = max(1, int(size or 1))
    overlap = max(0, min(int(overlap or 0), size - 1))
    if not text:
        return []
    step = size - overlap
    out = []
    i = 0
    while i < len(text):
        piece = text[i : i + size].strip()
        if piece:
            out.append(piece)
        if i + size >= len(text):
            break
        i += step
    return out

def _chunk_hierarchical(config, inputs, types):
    text = _text(inputs.get("input"))
    parent = int(_cfg(config, "parent_size", 2000) or 2000)
    child = int(_cfg(config, "child_size", 400) or 400)
    out = []
    for pi, p in enumerate(_split_chunks(text, parent, 0)):
        pid = _chunk_id(p, pi)
        out.append(_T(types, "Chunk", text=p, chunk_id=pid, metadata={"role": "parent"}))
        for ci, c in enumerate(_split_chunks(p, child, 0)):
            out.append(
                _T(types, "Chunk", text=c, chunk_id=_chunk_id(c, ci), metadata={"role": "child", "parent_id": pid})
            )
    return out



class ChunkHierarchicalNode(Node):
    """Parent/child hierarchical chunks"""

    node_type: ClassVar[str] = "chunk_hierarchical"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="chunk_hierarchical",
        label="Chunk Hierarchical",
        description="Parent/child hierarchical chunks",
        category="Processing",
        version="0.1.0",
        tags=["rag"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[RawDocument] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[Chunk]"),
        "parents": OutputPort(name="parents", data_type=object, description="list[Chunk]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        parent_size: int = Field(default=2000, title="Parent size", description="Parent size.")
        child_size: int = Field(default=400, title="Child size", description="Child size.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'rag' / 'chunk_hierarchical'
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
            result = {
                "output": [],
                "parents": [],
            }
            return result
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"chunk_hierarchical: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _chunk_hierarchical(self.config, inputs, _types)}
