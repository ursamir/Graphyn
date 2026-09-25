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

REPO_ROOT = Path(__file__).resolve().parents[2]
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
            candidates: list[tuple[int, int, int, str, str]] = []
            for src_i in range(dst_i - 1, -1, -1):
                _, souts = _catalog_ports(node_types[src_i])
                for sout in souts:
                    score = _compatibility_score(sout["type"], din["type"])
                    if score <= 0:
                        continue
                    distance = dst_i - src_i
                    candidates.append((score, -distance, src_i, sout["name"], din["name"]))
            if candidates:
                candidates.sort(reverse=True)
                _score, _negdist, src_i, sport, dport = candidates[0]
                add(src_i, sport, dst_i, dport)
                bound.add(din["name"])
        # If nothing bound, fall back to previous node → first input
        if not bound:
            src_i = dst_i - 1
            _, souts = _catalog_ports(node_types[src_i])
            add(src_i, souts[0]["name"] if souts else "output", dst_i, dins[0]["name"])
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


def _alias_port(port: str, available: list[str] | None = None) -> str:
    if available and port in available:
        return port
    alt = _PORT_ALIASES.get(port)
    if alt and (available is None or alt in available):
        return alt
    return port

def materialize_template_entry(entry: dict[str, Any], *, merge_parameters_into_first: bool = False) -> dict[str, Any]:
    """Expand a catalog entry into schema_version 1.1 graph dict."""
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
