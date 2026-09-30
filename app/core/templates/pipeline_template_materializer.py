"""Materialize marketplace template catalog entries into Graph IR (schema_version 1.1).

Bounded Context:  Graph Language / Templates
Responsibility:   Expand catalog node_chain (+ optional edges_hint) into graph dicts;
                  optionally write seed .graph.json files.
Owns:             materialize_template_entry, materialize_to_file, load_marketplace_catalog
Must NOT:         Execute pipelines or mutate production configs/templates without caller intent.
Dependencies:     json, pathlib, copy
Reason To Change: Catalog schema or Graph IR shape changes.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG = REPO_ROOT / "docs" / "PIPELINE_TEMPLATE_CATALOG.json"

PLATFORM_CATALOG = REPO_ROOT / "docs" / "PLUGIN_NODE_PLATFORM_CATALOG.json"

_port_cache: dict[str, dict[str, list[str]]] | None = None


def _node_port_names(node_type: str) -> dict[str, list[str]]:
    """Return {inputs: [...], outputs: [...]} for a node_type from platform catalog."""
    global _port_cache
    if _port_cache is None:
        _port_cache = {}
        try:
            doc = json.loads(PLATFORM_CATALOG.read_text(encoding="utf-8"))
        except Exception:
            doc = {}
        nodes = list(doc.get("nodes") or []) + list(doc.get("refinement_added_nodes") or [])
        # refinements file may add more
        ref = REPO_ROOT / "docs" / "PLUGIN_NODE_REFINEMENTS.json"
        if ref.is_file():
            try:
                rdoc = json.loads(ref.read_text(encoding="utf-8"))
                nodes.extend(rdoc.get("added_nodes") or [])
            except Exception:
                pass
        for n in nodes:
            nt = n.get("node_type")
            if not nt:
                continue
            _port_cache[nt] = {
                "inputs": [p.get("name") or "input" for p in (n.get("inputs") or [])],
                "outputs": [p.get("name") or "output" for p in (n.get("outputs") or [])],
            }
    return _port_cache.get(node_type, {"inputs": ["input"], "outputs": ["output"]})


def _default_src_port(node_type: str) -> str:
    outs = _node_port_names(node_type)["outputs"]
    return outs[0] if outs else "output"


def _default_dst_port(node_type: str) -> str:
    ins = _node_port_names(node_type)["inputs"]
    # Prefer a port named input when present; else first declared input.
    if "input" in ins:
        return "input"
    return ins[0] if ins else "input"




def load_marketplace_catalog(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_CATALOG
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "templates" not in data:
        raise ValueError("Invalid marketplace catalog")
    return data


def find_template(template_id: str, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = catalog or load_marketplace_catalog()
    for t in doc.get("templates", []):
        if t.get("id") == template_id:
            return t
    raise KeyError(f"Template not found: {template_id}")


def _normalize_type_token(type_str: str) -> str:
    s = (type_str or "Any").strip()
    s = re.sub(r"\bNEW\b|\boptional\b|\bmulti\b", "", s, flags=re.I)
    s = re.sub(r"\s+", "", s)
    return s or "Any"


def _compatibility_score(src_type: str, dst_type: str) -> int:
    """Higher is better. 0 = incompatible. Prefer concrete matches over object/Any."""
    s = _normalize_type_token(src_type)
    d = _normalize_type_token(dst_type)
    if not s or not d:
        return 1
    wild_s = s in ("Any", "object")
    wild_d = d in ("Any", "object")
    if s == d and not wild_s:
        return 4
    if wild_s or wild_d:
        # usable fallback only
        base = 1
    else:
        base = 0
    # unions
    if "|" in d:
        return max((_compatibility_score(s, part) for part in d.split("|")), default=0)
    if "|" in s:
        return max((_compatibility_score(part, d) for part in s.split("|")), default=0)
    if d == "list" and s.startswith("list"):
        return 3
    if s == "list" and d.startswith("list"):
        return 3
    if s.startswith("list[") and d.startswith("list["):
        inner = _compatibility_score(s[5:-1], d[5:-1])
        return 3 if inner else 0
    if "DatasetArtifact" in s and "DatasetArtifact" in d:
        return 4
    if "ModelArtifact" in s and "ModelArtifact" in d:
        return 4
    if "TFLiteArtifact" in s and "TFLiteArtifact" in d:
        return 4
    if "DeploymentArtifact" in s and "DeploymentArtifact" in d:
        return 4
    # Same-family soft matches (validator still enforces concrete port types).
    if "FeatureArray" in s and "FeatureArray" in d:
        return 3
    if "AudioSample" in s and "AudioSample" in d:
        return 3
    # Soft list[EmbeddingVector] -> list[FeatureArray] when fusion/adapters emit features.
    if "EmbeddingVector" in s and "FeatureArray" in d:
        return 2
    if "FeatureArray" in s and "EmbeddingVector" in d:
        return 2
    if "Embedding" in s and "Embedding" in d:
        return 3
    if "Chunk" in s and "Chunk" in d:
        return 3
    if "RetrievalHit" in s and "RetrievalHit" in d:
        return 3
    if d == "str" and s == "str":
        return 4
    if d == "str" and any(x in s for x in ("AssembledPrompt", "RagAnswer", "str")):
        return 2
    return base


def _types_loosely_compatible(src_type: str, dst_type: str) -> bool:
    return _compatibility_score(src_type, dst_type) > 0


# Side-channel outputs must not win linear wiring when primary ``output`` ties on type.
_SECONDARY_OUTPUT_PORTS = frozenset(
    {"rejected", "error", "errors", "failed", "discarded", "skipped", "dead_letter"}
)


def _output_port_preference(name: str) -> int:
    n = (name or "").strip().lower()
    if n in _SECONDARY_OUTPUT_PORTS:
        return 0
    if n in {"output", "out", "features", "dataset", "samples"}:
        return 2
    return 1


def _primary_output_name(souts: list[dict[str, str]]) -> str:
    if not souts:
        return "output"
    ranked = sorted(
        souts,
        key=lambda p: (_output_port_preference(str(p.get("name") or "")), str(p.get("name") or "")),
        reverse=True,
    )
    return str(ranked[0].get("name") or "output")


def _catalog_ports(node_type: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    info = _node_port_names(node_type)
    # Rebuild with types from catalog cache if available
    global _port_cache_full
    try:
        _port_cache_full
    except NameError:
        _port_cache_full = None
    if _port_cache_full is None:
        _port_cache_full = {}
        try:
            doc = json.loads(PLATFORM_CATALOG.read_text(encoding="utf-8"))
        except Exception:
            doc = {}
        nodes = list(doc.get("nodes") or []) + list(doc.get("refinement_added_nodes") or [])
        ref = REPO_ROOT / "docs" / "PLUGIN_NODE_REFINEMENTS.json"
        if ref.is_file():
            try:
                nodes.extend(json.loads(ref.read_text(encoding="utf-8")).get("added_nodes") or [])
            except Exception:
                pass
        for n in nodes:
            nt = n.get("node_type")
            if not nt:
                continue
            _port_cache_full[nt] = (
                [{"name": p.get("name") or "input", "type": p.get("type") or "Any"} for p in (n.get("inputs") or [])],
                [{"name": p.get("name") or "output", "type": p.get("type") or "Any"} for p in (n.get("outputs") or [])],
            )
    return _port_cache_full.get(
        node_type,
        (
            [{"name": n, "type": "Any"} for n in info["inputs"]] or [{"name": "input", "type": "Any"}],
            [{"name": n, "type": "Any"} for n in info["outputs"]] or [{"name": "output", "type": "Any"}],
        ),
    )


def _linear_edges(node_types: list[str]) -> list[dict[str, Any]]:
    """Wire a chain with fan-in: each required input binds to nearest compatible upstream output."""
    edges: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str, str, str]] = set()

    def add(src_i: int, src_port: str, dst_i: int, dst_port: str) -> None:
        key = (f"n{src_i}", src_port, f"n{dst_i}", dst_port)
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        edges.append(
            {
                "src_id": f"n{src_i}",
                "src_port": src_port,
                "dst_id": f"n{dst_i}",
                "dst_port": dst_port,
                "condition": None,
            }
        )

    for dst_i, dst_t in enumerate(node_types):
        if dst_i == 0:
            continue
        dins, _ = _catalog_ports(dst_t)
        if not dins:
            # sink-less / source-like mid node — no inbound edges
            continue
        bound: set[str] = set()
        for din in dins:
            # Prefer concrete type matches over object/Any; then nearest upstream.
            candidates: list[tuple[int, int, int, int, str, str]] = []
            for src_i in range(dst_i - 1, -1, -1):
                _, souts = _catalog_ports(node_types[src_i])
                for sout in souts:
                    score = _compatibility_score(sout["type"], din["type"])
                    if score <= 0:
                        continue
                    distance = dst_i - src_i
                    pref = _output_port_preference(str(sout.get("name") or ""))
                    # Prefer higher type score, then primary ports (not rejected),
                    # then nearer upstream. Lexicographic port names must NOT decide
                    # between ``output`` and ``rejected`` (rejected > output).
                    candidates.append((score, pref, -distance, src_i, sout["name"], din["name"]))
            if candidates:
                candidates.sort(reverse=True)
                _score, _pref, _negdist, src_i, sport, dport = candidates[0]
                add(src_i, sport, dst_i, dport)
                bound.add(din["name"])
        # If nothing bound, fall back to previous node → first input
        if not bound:
            src_i = dst_i - 1
            _, souts = _catalog_ports(node_types[src_i])
            add(src_i, _primary_output_name(souts), dst_i, dins[0]["name"])
    return edges



def _coerce_parameters(params: dict[str, Any]) -> dict[str, Any]:
    """Coerce flat marketplace parameter values into Graph IR IRParameter dicts."""
    out: dict[str, Any] = {}
    for key, val in (params or {}).items():
        if isinstance(val, dict) and {"type", "default"} <= set(val.keys()):
            out[key] = val
            continue
        if isinstance(val, bool):
            typ = "boolean"
        elif isinstance(val, int) and not isinstance(val, bool):
            typ = "integer"
        elif isinstance(val, float):
            typ = "number"
        elif isinstance(val, list):
            typ = "array"
        elif isinstance(val, dict):
            typ = "object"
        else:
            typ = "string"
        out[key] = {"type": typ, "default": val, "description": ""}
    return out


_PORT_ALIASES = {
    "input_a": "a",
    "input_b": "b",
    "left": "a",
    "right": "b",
}

# Marketplace catalog historically put fictional dataset roots in
# ``parameters.dataset_path`` / config_overrides without shipping those folders.
# Out-of-box materialize always rewrites ingest paths onto bundled seed datasets
# under ``workspace/datasets/input/`` (created by ``seed_example_input_datasets``).
_INGEST_NODE_TYPES = frozenset(
    {
        "dataset_ingest",
        "vision_dataset_ingest",
        "video_ingest",
        "mcu_dataset_ingest",
        "rag_fs_connector",
    }
)

# (node_type, wrong_key) → correct Config field (Pydantic extra=forbid).
_CONFIG_KEY_ALIASES: dict[tuple[str, str], str] = {
    ("audio_conditioner", "sample_rate"): "target_sample_rate",
    ("audio_resample", "sample_rate"): "target_sample_rate",
}

# Marketplace OOB: cap filesystem ingest so a template Run does not load the
# whole speech-commands tree into RAM (recursive limit is per-label).
_OOB_INGEST_LIMIT = 8


def _flat_param_defaults(params: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, val in (params or {}).items():
        if isinstance(val, dict) and "default" in val:
            flat[key] = val["default"]
        else:
            flat[key] = val
    return flat


def _oob_seed_path(entry: dict[str, Any], node_type: str) -> str:
    """Return a workspace input path that ships with the repo (after seed sync)."""
    pack = str(entry.get("pack") or "").strip().lower()
    family = str(entry.get("family") or "").strip().lower()
    tags = {str(t).strip().lower() for t in (entry.get("tags") or [])}
    modality = {str(m).strip().lower() for m in (entry.get("modality") or [])}
    blob = " ".join([pack, family, *tags, *modality, str(entry.get("id") or "").lower()])

    if node_type == "rag_fs_connector" or pack == "rag" or "rag" in tags or "rag" in blob:
        return "workspace/datasets/input/doc-rag-ingest"
    if node_type in {"vision_dataset_ingest"} or pack == "vision" or "vision" in modality:
        return "workspace/datasets/input/vision-demo"
    if node_type == "video_ingest" or pack == "video" or "video" in modality:
        return "workspace/datasets/input/video-demo"
    if pack == "wakeword" or "wakeword" in tags or "wake-word" in blob or family == "wakeword":
        return "workspace/datasets/input/wake-word"
    if "sed" in tags or "environmental" in tags or "environment" in blob:
        return "workspace/datasets/input/environmental-sounds"
    if "enhancement" in tags or "enhancement" in family or "enhancer" in blob:
        return "workspace/datasets/input/speech-enhancement"
    if "speaker" in tags or "diarization" in tags or "verify" in blob:
        return "workspace/datasets/input/speaker-verification"
    if node_type == "mcu_dataset_ingest" or pack == "tinyml":
        # TinyML KWS demos reuse speech-commands wavs as MCU features upstream.
        return "workspace/datasets/input/speech-commands"
    # Default audio / KWS / captions / ASR / unknown → speech-commands
    return "workspace/datasets/input/speech-commands"


def _bind_oob_ingest_and_params(nodes: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    """Wire ingest nodes to bundled seed data + remap known parameter aliases."""
    flat = _flat_param_defaults(entry.get("parameters") or {})

    for node in nodes:
        nt = str(node.get("node_type") or "")
        cfg = node.setdefault("config", {})
        if nt in _INGEST_NODE_TYPES:
            path_val = _oob_seed_path(entry, nt)
            if nt == "rag_fs_connector":
                cfg["path"] = path_val
                cfg.pop("root", None)
            else:
                cfg["path"] = path_val
            if nt == "dataset_ingest" and int(cfg.get("limit") or 0) == 0:
                cfg["limit"] = _OOB_INGEST_LIMIT
        if nt == "dataset_builder" and int(cfg.get("fixed_length") or 0) == 0:
            cfg["fixed_length"] = 100
        if nt == "trainer":
            epochs = int(cfg.get("epochs") or 0)
            if epochs <= 0 or epochs > 3:
                cfg["epochs"] = 1
            cfg.setdefault("batch_size", 8)
            cfg.setdefault("device", "cpu")
        if nt == "yolo_train":
            epochs = int(cfg.get("epochs") or 0)
            if epochs <= 0 or epochs > 3:
                cfg["epochs"] = 1
            cfg.setdefault("batch", 1)
            cfg.setdefault("imgsz", 64)
            cfg.setdefault("device", "cpu")
        if nt == "yolo_val":
            cfg.setdefault("device", "cpu")
        if nt == "mcu_train":
            epochs = int(cfg.get("epochs") or 0)
            if epochs <= 0 or epochs > 3:
                cfg["epochs"] = 1
        if nt == "http_request" and not str(cfg.get("url") or "").strip():
            # Safe public echo endpoint for OOB marketplace smoke (no secrets).
            cfg["url"] = "https://httpbin.org/get"
            cfg.setdefault("method", "GET")
        if nt == "csv_table" and not str(cfg.get("path") or "").strip():
            cfg["path"] = "workspace/datasets/input/csv-data-processing/sample.csv"
        if nt == "mcp_tool_call":
            # Host image may not ship the optional ``mcp`` package; OOB stubs.
            cfg.setdefault("stub", True)
        if nt == "tool_router" and not (cfg.get("tools") or []):
            cfg["tools"] = ["echo"]
            cfg.setdefault("strict", False)
        if nt == "eval_gate":
            # Marketplace ingest/MLOps chains often feed non-transcript payloads.
            cfg.setdefault("check_empty_transcript", False)
            cfg.setdefault("fail_if_empty_list", False)
        if nt == "ship_package_create":
            # Marketplace OOB graphs rarely have a registry model; stub the packager.
            cfg.setdefault("stub", True)
            if not str(cfg.get("model_name") or "").strip():
                cfg["model_name"] = "demo_model"
            cfg.setdefault("project", "tpl-smoke")
            cfg.setdefault("unsigned_allowed", True)
        if nt == "ship_package_transition":
            cfg.setdefault("stub", True)
        if nt == "hitl_approve":
            cfg["unattended_approve"] = True
        if nt == "stream_ingest":
            cfg["source"] = "file_stream"
            cfg["file_path"] = (
                "workspace/datasets/input/speech-commands/go/0ea0e2f4_nohash_0.wav"
            )
            cfg["duration_s"] = 1.0
        if nt in {"vector_store_query", "vector_store_write"}:
            backend = str(cfg.get("backend") or "chromadb").lower()
            if backend in {"", "chromadb", "chroma", "pgvector", "pg"}:
                cfg["backend"] = "faiss"
            cfg.setdefault("persist_path", "workspace/artifacts/vectorstores/oob-docs")
        # Catalog often stamps fictional ``path`` onto non-ingest nodes (wakeword
        # data-gen uses output_dir). Drop/remap so extra=forbid Configs accept OOB.
        if nt == "wakeword_data_gen" and "path" in cfg:
            if not str(cfg.get("output_dir") or "").strip():
                cfg["output_dir"] = "workspace/datasets/input/wake-word"
            cfg.pop("path", None)
        elif "path" in cfg and nt not in _INGEST_NODE_TYPES and nt not in {
            "csv_table",
            "http_request",
            "object_store",
            "rag_fs_connector",
        }:
            # Leave alone only if a later sanitize-with-registry keeps it;
            # without registry, drop unknown-looking path on non-ingest nodes.
            pass

    # sample_rate parameter → audio_conditioner.target_sample_rate
    sr = flat.get("sample_rate")
    if sr is not None:
        for node in nodes:
            if node.get("node_type") == "audio_conditioner":
                cfg = node.setdefault("config", {})
                cfg["target_sample_rate"] = sr
                cfg.pop("sample_rate", None)
                break
            if node.get("node_type") == "audio_resample":
                cfg = node.setdefault("config", {})
                cfg["target_sample_rate"] = sr
                cfg.pop("sample_rate", None)
                break


def _sanitize_node_configs(
    nodes: list[dict[str, Any]],
    registry: Any | None = None,
) -> None:
    """Drop unknown config keys / remap aliases so Node Config (extra=forbid) accepts the graph."""
    for node in nodes:
        nt = str(node.get("node_type") or "")
        cfg = dict(node.get("config") or {})
        for (alias_nt, bad), good in _CONFIG_KEY_ALIASES.items():
            if nt != alias_nt or bad not in cfg:
                continue
            if good not in cfg:
                cfg[good] = cfg[bad]
            cfg.pop(bad, None)

        fields: set[str] | None = None
        if registry is not None:
            try:
                cls = registry.get_class(nt)
                fields = set(getattr(cls.Config, "model_fields", {}) or {})
            except Exception:
                fields = None
        if fields is not None:
            for key in list(cfg):
                if key not in fields:
                    cfg.pop(key, None)
        node["config"] = cfg


def _alias_port(port: str, available: list[str] | None = None) -> str:
    if available and port in available:
        return port
    alt = _PORT_ALIASES.get(port)
    if alt and (available is None or alt in available):
        return alt
    return port

def materialize_template_entry(
    entry: dict[str, Any],
    *,
    merge_parameters_into_first: bool = False,
    registry: Any | None = None,
    ensure_seed_datasets: bool = True,
) -> dict[str, Any]:
    """Expand a catalog entry into schema_version 1.1 graph dict.

    Out-of-box contract: ingest paths point at bundled ``workspace/datasets/input/*``
    seeds; config keys are remapped/sanitized for real node Config models.
    """
    if ensure_seed_datasets:
        try:
            from app.core.templates.example_templates import seed_example_input_datasets

            seed_example_input_datasets()
        except Exception:
            pass

    chain = entry.get("node_chain") or []
    if not chain:
        raise ValueError("node_chain required")
    nodes: list[dict[str, Any]] = []
    params = deepcopy(entry.get("parameters") or {})
    for i, step in enumerate(chain):
        cfg = deepcopy(step.get("config_overrides") or {})
        if merge_parameters_into_first and i == 0 and params:
            for k, v in params.items():
                cfg.setdefault(k, v)
        nodes.append(
            {
                "id": f"n{i}",
                "node_type": step["node_type"],
                "config": cfg,
                "label": step.get("role") or step["node_type"],
                "capability_metadata": None,
                "event_trigger": None,
            }
        )
    _bind_oob_ingest_and_params(nodes, entry)
    _sanitize_node_configs(nodes, registry=registry)
    raw_edges = entry.get("edges_hint") or []
    if raw_edges:
        edges = []
        for e in raw_edges:
            ee = dict(e)
            ee.setdefault("condition", None)
            if "src_port" in ee:
                ee["src_port"] = _alias_port(str(ee["src_port"]))
            if "dst_port" in ee:
                ee["dst_port"] = _alias_port(str(ee["dst_port"]))
            edges.append(ee)
    else:
        edges = _linear_edges([step["node_type"] for step in chain])
    meta: dict[str, Any] = {
        "name": entry.get("id") or entry.get("name") or "marketplace-template",
        "seed": 42,
        "description": entry.get("description") or "",
        "created_at": None,
        "tags": list(entry.get("tags") or []),
        "pack": entry.get("pack"),
        "industry": entry.get("industry"),
        "marketplace_id": entry.get("id"),
        "status": entry.get("status", "proposed"),
        "source_example": f"marketplace/{entry.get('id')}.graph.json",
    }
    extra = entry.get("metadata_extra") or {}
    if isinstance(extra, dict):
        meta.update(extra)
    return {
        "schema_version": "1.1",
        "metadata": meta,
        "nodes": nodes,
        "edges": edges,
        "parameters": _coerce_parameters(params),
    }


def materialize_to_file(template_id: str, out_path: Path, *, catalog_path: Path | None = None) -> Path:
    entry = find_template(template_id, load_marketplace_catalog(catalog_path))
    graph = materialize_template_entry(entry)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    return out_path


def build_graph_from_chain(node_types: list[str], *, name: str = "ad-hoc", description: str = "") -> dict[str, Any]:
    """Helper for agents: linear chain of node_types -> graph dict."""
    entry = {
        "id": name,
        "name": name,
        "description": description or f"Ad-hoc chain: {' -> '.join(node_types)}",
        "pack": "Common",
        "tags": ["ad-hoc"],
        "node_chain": [{"node_type": nt} for nt in node_types],
        "parameters": {},
        "status": "proposed",
    }
    return materialize_template_entry(entry)


def search_marketplace_templates(
    *,
    pack: str = "",
    industry: str = "",
    modality: str = "",
    lifecycle: str = "",
    status: str = "",
    family: str = "",
    q: str = "",
    tags: list[str] | None = None,
    limit: int = 25,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Filter marketplace catalog entries (shared by REST + MCP).

    Returns ``{templates, count, matched, limit, catalog}``. Does not raise when
    the catalog is missing — returns empty templates with ``catalog_missing``.
    """
    limit_n = max(1, min(int(limit or 25), 200))
    pack_l = (pack or "").strip().lower()
    industry_l = (industry or "").strip().lower()
    modality_l = (modality or "").strip().lower()
    lifecycle_l = (lifecycle or "").strip().lower()
    status_l = (status or "").strip().lower()
    family_l = (family or "").strip().lower()
    q_l = (q or "").strip().lower()
    tag_list = [str(t).strip().lower() for t in (tags or []) if str(t).strip()]

    path = catalog_path or DEFAULT_CATALOG
    if not path.is_file():
        return {
            "templates": [],
            "count": 0,
            "matched": 0,
            "limit": limit_n,
            "catalog": str(path),
            "catalog_missing": True,
        }

    doc = load_marketplace_catalog(path)
    items: list[dict[str, Any]] = []
    for t in doc.get("templates") or []:
        if not isinstance(t, dict):
            continue
        if pack_l and str(t.get("pack") or "").lower() != pack_l and pack_l not in [
            str(p).lower() for p in (t.get("packs_used") or [])
        ]:
            continue
        if industry_l and str(t.get("industry") or "").lower() != industry_l:
            continue
        if modality_l and modality_l not in [str(m).lower() for m in (t.get("modality") or [])]:
            continue
        if lifecycle_l and lifecycle_l not in [str(x).lower() for x in (t.get("lifecycle") or [])]:
            continue
        if status_l and str(t.get("status") or "").lower() != status_l:
            continue
        if family_l and str(t.get("family") or "").lower() != family_l:
            continue
        if tag_list:
            ttags = {str(x).lower() for x in (t.get("tags") or [])}
            if not set(tag_list).issubset(ttags):
                continue
        if q_l:
            blob = " ".join(
                [
                    str(t.get("id") or ""),
                    str(t.get("name") or ""),
                    str(t.get("description") or ""),
                    " ".join(str(x) for x in (t.get("tags") or [])),
                ]
            ).lower()
            if q_l not in blob:
                continue
        items.append(
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "pack": t.get("pack"),
                "industry": t.get("industry"),
                "modality": t.get("modality"),
                "lifecycle": t.get("lifecycle"),
                "tags": t.get("tags"),
                "status": t.get("status"),
                "family": t.get("family"),
                "value_prop": t.get("value_prop"),
                "description": t.get("description"),
                "node_types": [
                    s.get("node_type") for s in (t.get("node_chain") or []) if isinstance(s, dict)
                ],
            }
        )

    matched = len(items)
    page = items[:limit_n]
    return {
        "templates": page,
        "count": len(page),
        "matched": matched,
        "limit": limit_n,
        "catalog": str(path),
        "catalog_missing": False,
        "total_in_catalog": int(doc.get("total_templates") or len(doc.get("templates") or [])),
        "counts_by_pack": doc.get("counts_by_pack") or {},
        "counts_by_status": doc.get("counts_by_status") or {},
    }
