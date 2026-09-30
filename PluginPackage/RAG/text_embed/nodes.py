"""TextEmbedNode — Text embeddings for chunks

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any, Literal
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort


def _force_cpu() -> None:
    """Stay on CPU when another process owns the GPU. Default on."""
    import os

    flag = os.environ.get("GRAPHYN_ML_FORCE_CPU", "1").strip().lower()
    if flag in ("0", "false", "no"):
        return
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("text_embed.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Chunk = _types.Chunk
EmbeddingVector = _types.EmbeddingVector

log = logging.getLogger(__name__)


class TextEmbedNode(Node):
    """Text embeddings for chunks"""

    node_type: ClassVar[str] = "text_embed"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="text_embed",
        label="Text Embed",
        description="Text embeddings for chunks",
        category="Features",
        version="0.2.0",
        tags=["rag"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[Chunk]|list[str]"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[EmbeddingVector]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        backend: Literal["sentence_transformers", "openai"] = Field(default="sentence_transformers", title="Backend", description="sentence_transformers (local). openai is declared but not implemented yet and raises.")
        model_name_or_path: str = Field(default='sentence-transformers/all-MiniLM-L6-v2', title="Model name or path", description="Model name or path.")
        normalize: bool = Field(default=True, title="Normalize", description="Normalize.")
        api_secret_name: str = Field(default='OPENAI_API_KEY', title="Api secret name", description="Api secret name.")


    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        stub = bool(getattr(self.config, 'stub', False))
        raw = inputs.get("input") or []
        if not isinstance(raw, list):
            raw = [raw]
        if stub:
            out = []
            for i, item in enumerate(raw):
                text = getattr(item, "text", None) or (item if isinstance(item, str) else "")
                out.append(
                    EmbeddingVector(
                        embedding=[0.0] * 8,
                        source_path=str(getattr(item, "source", "") or ""),
                        label="",
                        metadata={"stub": True, "i": i, "chars": len(text or "")},
                    )
                )
            return {"output": out}
        backend = str(getattr(self.config, "backend", "sentence_transformers") or "sentence_transformers")
        if backend != "sentence_transformers":
            raise NotImplementedError(f"text_embed: backend {backend!r} is not implemented; use sentence_transformers")
        try:
            _force_cpu()
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed in this plugin venv. "
                "Use Plugins → Install optional (venv)."
            ) from exc
        model = SentenceTransformer(str(getattr(self.config, "model_name_or_path", "sentence-transformers/all-MiniLM-L6-v2")))
        texts = [getattr(x, "text", None) or (x if isinstance(x, str) else str(x)) for x in raw]
        vectors = model.encode(texts, normalize_embeddings=bool(getattr(self.config, "normalize", True)))
        out = []
        for i, vec in enumerate(vectors):
            out.append(EmbeddingVector(embedding=vec, source_path="", label="", metadata={"i": i}))
        return {"output": out}

