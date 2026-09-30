"""Regression tests for RAG / Vision enum-schema lint fixes and zero-valued numeric config."""
from __future__ import annotations

import sys
import typing
from pathlib import Path

import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "PluginPackage"


def _load(rel: str, node_type: str):
    root = PKG / rel
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    for entry in ("types.py", "nodes.py"):
        if (root / entry).is_file():
            disc._process_module(disc._import_file(root / entry, package_prefix=None))
    return reg.get_class(node_type)


ENUM_FIELDS = [
    ("RAG/bm25_index_build", "bm25_index_build", "backend"),
    ("RAG/contextual_compress", "contextual_compress", "backend"),
    ("RAG/kg_light_extract", "kg_light_extract", "backend"),
    ("RAG/rag_rerank", "rag_rerank", "backend"),
    ("RAG/text_embed", "text_embed", "backend"),
    ("RAG/vector_store_query", "vector_store_query", "backend"),
    ("RAG/vector_store_write", "vector_store_write", "backend"),
    ("Vision/tensorrt_infer", "tensorrt_infer", "device"),
    ("Vision/vision_dataset_ingest", "vision_dataset_ingest", "source_type"),
    ("Vision/yolo_predict", "yolo_predict", "device"),
    ("Vision/yolo_train", "yolo_train", "device"),
    ("MLOps/drift_detect", "drift_detect", "method"),
    ("MLOps/artifact_checksum", "artifact_checksum", "algo"),
]


@pytest.mark.parametrize("rel, node_type, key", ENUM_FIELDS)
def test_enum_toml_matches_literal(rel, node_type, key):
    cls = _load(rel, node_type)
    spec = tomllib.loads((PKG / rel / "plugin.toml").read_text())["config_schema"][node_type][key]
    field = cls.Config.model_fields[key]
    assert typing.get_origin(field.annotation) is typing.Literal
    assert list(typing.get_args(field.annotation)) == spec["enum"]
    assert spec["default"] == field.default


def test_kg_light_extract_llm_backend_is_honest():
    cls = _load("RAG/kg_light_extract", "kg_light_extract")
    out = cls(config={}).process({"input": "Paris is capital. Water is wet."})["output"]
    meta = out["metadata"] if isinstance(out, dict) else out.metadata
    assert meta["backend"] == "pattern"
    with pytest.raises(NotImplementedError):
        cls(config={"backend": "llm"}).process({"input": "Paris is capital."})


def test_text_embed_openai_backend_is_honest():
    cls = _load("RAG/text_embed", "text_embed")
    with pytest.raises(NotImplementedError):
        cls(config={"backend": "openai"}).process({"input": ["hello"]})


def test_contextual_compress_truncate_keeps_order():
    cls = _load("RAG/contextual_compress", "contextual_compress")
    hits = [{"chunk_id": "1", "text": "zzz " * 50}, {"chunk_id": "2", "text": "query words here"}]
    out = cls(config={"backend": "truncate", "max_chars": 10}).process({"hits": hits, "query": "query"})["output"]
    texts = [(h["text"] if isinstance(h, dict) else h.text) for h in out]
    assert texts == ["zzz zzz zz", "query word"]


def test_rag_rerank_default_bm25_works_without_deps():
    cls = _load("RAG/rag_rerank", "rag_rerank")
    hits = [{"chunk_id": "a", "text": "cats and dogs"}, {"chunk_id": "b", "text": "stock market"}]
    out = cls(config={}).process({"hits": hits, "query": "market"})["output"]
    first = out[0]["chunk_id"] if isinstance(out[0], dict) else out[0].chunk_id
    assert first == "b"


def test_vision_ingest_yolo_layout(tmp_path):
    cls = _load("Vision/vision_dataset_ingest", "vision_dataset_ingest")
    (tmp_path / "images").mkdir()
    (tmp_path / "labels").mkdir()
    (tmp_path / "images" / "a.jpg").write_bytes(b"\xff\xd8")
    (tmp_path / "labels" / "a.txt").write_text("2 0.5 0.5 0.1 0.2\n")
    out = cls(config={"source_type": "yolo", "path": str(tmp_path)}).process({})["output"]
    assert len(out) == 1
    s = out[0]
    boxes = s["boxes"] if isinstance(s, dict) else s.boxes
    assert boxes == [{"class_id": 2, "xywhn": [0.5, 0.5, 0.1, 0.2]}]


def test_zero_config_values_are_respected():
    """``float(x or default)`` made 0 impossible; 0 must now stay 0."""
    cls = _load("RAG/hybrid_retrieve", "hybrid_retrieve")
    mod = sys.modules[cls.__module__]
    assert mod._num_or(0, 0.5) == 0 and mod._num_or(None, 0.5) == 0.5
    nms = _load("Vision/yolo_nms_postprocess", "yolo_nms_postprocess")
    nmod = sys.modules[nms.__module__]
    assert nmod._num_or(0.0, 0.25) == 0.0
