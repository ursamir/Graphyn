"""Bm25IndexBuildNode — Build BM25 sparse index for hybrid retrieval

Default config.stub=False builds the index.
When stub=False, builds a pure-Python Okapi BM25 index (no rank_bm25 required)
and persists corpus + tokenized docs for hybrid_retrieve.
"""
from __future__ import annotations

import importlib
import json
import logging
import math
import re
from collections import Counter
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
        _types = importlib.import_module("bm25_index_build.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Chunk = _types.Chunk
SparseIndexRef = _types.SparseIndexRef

log = logging.getLogger(__name__)


def _num_or(value, default):
    """Config numeric with a real default: only None falls back (0 stays 0)."""
    return default if value is None or value == "" else value

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _as_list(val: Any) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _chunk_text(item: Any) -> tuple[str, str]:
    if isinstance(item, str):
        return item, ""
    text = getattr(item, "text", None)
    cid = getattr(item, "chunk_id", None) or ""
    if text is None and isinstance(item, dict):
        text = item.get("text") or ""
        cid = item.get("chunk_id") or cid
    return str(text or ""), str(cid or "")


class Bm25IndexBuildNode(Node):
    """Build BM25 sparse index for hybrid retrieval"""

    node_type: ClassVar[str] = "bm25_index_build"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="bm25_index_build",
        label="Bm25 Index Build",
        description="Build BM25 sparse index for hybrid retrieval",
        category="Index",
        version="0.2.0",
        tags=["rag"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[Chunk]"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="SparseIndexRef"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        backend: Literal["rank_bm25", "pure_python"] = Field(default="rank_bm25", title="Backend", description="rank_bm25 (library) or pure_python BM25.")
        k1: float = Field(default=1.5, title="K1", description="K1.")
        b: float = Field(default=0.75, title="B", description="B.")
        persist_path: str = Field(default='workspace/artifacts/sparse/bm25', title="Persist path", description="Persist path.")

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path(getattr(self.config, "persist_path", None) or "workspace/artifacts/sparse/bm25")
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if stub:
            return {"output": SparseIndexRef(path=str(out_dir), backend="bm25", metadata={"stub": True})}
        return self._process_real(inputs, out_dir)

    def _process_real(self, inputs: dict, out_dir: Path):
        chunks = _as_list(inputs.get("input") or inputs.get("chunks"))
        texts: list[str] = []
        ids: list[str] = []
        for i, item in enumerate(chunks):
            text, cid = _chunk_text(item)
            texts.append(text)
            ids.append(cid or f"chunk-{i}")

        k1 = float(_num_or(getattr(self.config, "k1", 1.5), 1.5))
        b = float(_num_or(getattr(self.config, "b", 0.75), 0.75))
        backend = str(getattr(self.config, "backend", "rank_bm25") or "rank_bm25").lower()

        tokenized = [_tokenize(t) for t in texts]
        N = len(tokenized) or 1
        avgdl = (sum(len(d) for d in tokenized) / N) if tokenized else 0.0
        df: Counter[str] = Counter()
        for doc in tokenized:
            df.update(set(doc))
        idf = {term: math.log(1.0 + (N - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}

        # Optional rank_bm25 if present and requested — still persist our portable format.
        used = "pure_python"
        if backend in ("rank_bm25", "rank-bm25"):
            try:
                from rank_bm25 import BM25Okapi  # type: ignore

                _ = BM25Okapi(tokenized) if tokenized else None
                used = "rank_bm25"
            except ImportError:
                used = "pure_python"

        payload = {
            "backend": used,
            "k1": k1,
            "b": b,
            "avgdl": avgdl,
            "N": len(tokenized),
            "idf": idf,
            "docs": tokenized,
            "texts": texts,
            "ids": ids,
            "stub": False,
        }
        index_path = out_dir / "bm25_index.json"
        index_path.write_text(json.dumps(payload), encoding="utf-8")
        meta = {
            "stub": False,
            "backend": used,
            "n_docs": len(texts),
            "vocab": len(idf),
            "k1": k1,
            "b": b,
            "index_file": str(index_path),
        }
        (out_dir / "index_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        log.info("bm25_index_build wrote %d docs → %s (%s)", len(texts), index_path, used)
        return {"output": SparseIndexRef(path=str(out_dir), backend=used, metadata=meta)}
