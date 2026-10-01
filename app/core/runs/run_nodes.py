# app/core/runs/run_nodes.py
"""
Bounded Context:  BC6 — Observability & Storage (run read models)
Responsibility:   Registry-free read models for run detail: the run graph's
                  nodes in execution order (with per-node status) and a
                  consistent ``error`` field on persisted error log entries.
Owns:             graph_node_order, run_node_order, normalize_log_errors.
Public Surface:   graph_node_order(graph) → list[dict];
                  run_node_order(graph, meta) → list[dict];
                  normalize_log_errors(logs) → list.
Must NOT:         Import the node registry / planner (works for graphs whose
                  node types are no longer installed), execute nodes, or
                  write run state.
Dependencies:     stdlib (collections) only.
Reason To Change: Run detail response shape or execution-order policy changes.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def graph_node_order(graph: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Graph IR nodes in execution order (wave-major, like the planner).

    Each item: ``{node_id, node_type, label, index, wave}`` where ``index`` is
    the position in execution order. Ties inside a wave keep the IR's node
    order. Nodes on a cycle (invalid graph) are appended in IR order with
    ``wave: None``. Edges to unknown ids are ignored.
    """
    if not isinstance(graph, dict):
        return []
    raw_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    nodes: list[dict[str, Any]] = []
    ids: list[str] = []
    for i, node in enumerate(raw_nodes):
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id") or f"{node.get('node_type', 'node')}_{i}")
        if nid in ids:
            continue
        ids.append(nid)
        nodes.append(node)
    pos = {nid: i for i, nid in enumerate(ids)}
    preds: dict[str, list[str]] = defaultdict(list)
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("src_id") or "")
        dst = str(edge.get("dst_id") or "")
        if src in pos and dst in pos and src != dst:
            preds[dst].append(src)

    level: dict[str, int] = {}
    remaining = list(ids)
    progressed = True
    while remaining and progressed:
        progressed = False
        for nid in list(remaining):
            if all(p in level for p in preds[nid]):
                level[nid] = max((level[p] + 1 for p in preds[nid]), default=0)
                remaining.remove(nid)
                progressed = True

    ordered = sorted(level, key=lambda n: (level[n], pos[n])) + remaining
    by_id = dict(zip(ids, nodes))
    out: list[dict[str, Any]] = []
    for index, nid in enumerate(ordered):
        node = by_id[nid]
        out.append(
            {
                "node_id": nid,
                "node_type": str(node.get("node_type") or ""),
                "label": node.get("label") or None,
                "index": index,
                "wave": level.get(nid),
            }
        )
    return out


def run_node_order(
    graph: dict[str, Any] | None, meta: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """:func:`graph_node_order` plus ``status`` from ``meta.node_stats``.

    Nodes without a stats row get ``status: "not_run"``.
    """
    stats: dict[str, str] = {}
    rows = (meta or {}).get("node_stats") if isinstance(meta, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("node_id"):
            stats[str(row["node_id"])] = str(row.get("status") or "unknown")
    out = graph_node_order(graph)
    for item in out:
        item["status"] = stats.get(item["node_id"], "not_run")
    return out


def normalize_log_errors(logs: Any) -> Any:
    """Copy of run log entries where every error entry has ``error``.

    ``node_error`` entries written before the logger emitted ``error`` only
    carry ``error_message``; terminal ``error`` entries carry ``message``.
    Non-list input is returned unchanged.
    """
    if not isinstance(logs, list):
        return logs
    out: list[Any] = []
    for entry in logs:
        if isinstance(entry, dict) and entry.get("type") in ("node_error", "error"):
            if not entry.get("error"):
                msg = entry.get("error_message") or entry.get("message")
                if msg:
                    entry = {**entry, "error": str(msg)}
        out.append(entry)
    return out
