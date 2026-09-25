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
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = REPO_ROOT / "docs" / "PIPELINE_TEMPLATE_CATALOG.json"


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


def _linear_edges(n: int) -> list[dict[str, Any]]:
    return [
        {"src_id": f"n{i}", "src_port": "output", "dst_id": f"n{i+1}", "dst_port": "input", "condition": None}
        for i in range(n - 1)
    ]


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
            edges.append(ee)
    else:
        edges = _linear_edges(len(nodes))
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
        "parameters": params,
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
