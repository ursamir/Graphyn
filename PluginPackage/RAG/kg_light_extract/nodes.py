"""KgLightExtractNode — Light entity/relation extract

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import json
import re

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
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
        _types = importlib.import_module("kg_light_extract.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Chunk = _types.Chunk
KnowledgeGraphFragment = _types.KnowledgeGraphFragment
RagAnswer = _types.RagAnswer

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

def _kg_extract(config, inputs, types):
    backend = str(_cfg(config, "backend", "pattern") or "pattern")
    if backend != "pattern":
        raise NotImplementedError(f"kg_light_extract: backend {backend!r} is not implemented; use pattern")
    text = _text(inputs.get("input"))
    # Lightweight triple extraction: "A is B" / "A of B".
    triples = []
    for sent in re.split(r"[.!?]\s+", text):
        m = re.search(r"([A-Z][\w ]{1,40})\s+(is|are|of|has)\s+([A-Za-z][\w ]{1,40})", sent)
        if m:
            triples.append({"subject": m.group(1).strip(), "relation": m.group(2), "object": m.group(3).strip()})
    entities = sorted({t["subject"] for t in triples} | {t["object"] for t in triples})
    return _T(
        types,
        "KnowledgeGraphFragment",
        entities=entities,
        relations=triples,
        metadata={"n": len(triples), "backend": str(_cfg(config, "backend", "pattern"))},
    )



class KgLightExtractNode(Node):
    """Light entity/relation extract"""

    node_type: ClassVar[str] = "kg_light_extract"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="kg_light_extract",
        label="Kg Light Extract",
        description="Light entity/relation extract",
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
        "input": InputPort(name="input", data_type=object, required=True, description="list[Chunk]|RagAnswer NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="KnowledgeGraphFragment NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        backend: Literal["pattern", "llm"] = Field(default="pattern", title="Backend", description="pattern: regex triple extraction. llm is declared but not implemented yet and raises.")
        entity_schema: dict = Field(
            default_factory=dict,
            title="Entity schema",
            description="Optional entity/relation schema hints for extraction.",
        )
        api_secret_name: str = Field(default='OPENAI_API_KEY', title="Api secret name", description="Api secret name.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'rag' / 'kg_light_extract'
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
            result = KnowledgeGraphFragment()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"kg_light_extract: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _kg_extract(self.config, inputs, _types)}
