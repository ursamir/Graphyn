# app/core/agentic/proposals.py
"""
Bounded Context:  BC — Agentic Builder
Responsibility:   Persist GraphIR change proposals and compute simple diffs
                  for human-in-the-loop approval (propose → accept/reject).
Owns:             proposals/ store under project_dir, create/list/get/accept/reject,
                  diff_graphs().
Public Surface:   create_proposal, list_proposals, get_proposal, accept_proposal,
                  reject_proposal, diff_graphs, proposals_dir.
Must NOT:         Import from app.api; call an LLM; embed secrets in IR.
Dependencies:     stdlib, app.core.config.project_dir, app.core.audit.record_audit.
Reason To Change: Proposal schema evolves or diff granularity changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()

VALID_STATUSES = frozenset({"pending", "accepted", "rejected"})


def proposals_dir(base_dir: str | Path | None = None) -> Path:
    """Return ``{project}/proposals`` (or ``{base_dir}/proposals``)."""
    if base_dir is not None:
        return Path(base_dir) / "proposals"
    from app.core.config import project_dir

    return project_dir() / "proposals"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _graph_hash(graph: dict[str, Any] | None) -> str | None:
    if not isinstance(graph, dict) or not graph:
        return None
    try:
        payload = json.dumps(graph, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _node_map(graph: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(graph, dict):
        return out
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return out
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        if isinstance(nid, str) and nid.strip():
            out[nid] = node
    return out


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str, str, str | None]:
    cond = edge.get("condition")
    if cond is not None:
        cond = str(cond)
    return (
        str(edge.get("src_id") or ""),
        str(edge.get("src_port") or ""),
        str(edge.get("dst_id") or ""),
        str(edge.get("dst_port") or ""),
        cond,
    )


def _edge_set(graph: dict[str, Any] | None) -> set[tuple[str, str, str, str, str | None]]:
    out: set[tuple[str, str, str, str, str | None]] = set()
    if not isinstance(graph, dict):
        return out
    edges = graph.get("edges")
    if not isinstance(edges, list):
        return out
    for edge in edges:
        if isinstance(edge, dict):
            out.add(_edge_key(edge))
    return out


def _config_keys(node: dict[str, Any]) -> set[str]:
    cfg = node.get("config")
    if isinstance(cfg, dict):
        return set(cfg.keys())
    return set()


def _node_changed(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True if type or any config key/value differs (simple JSON compare)."""
    at = a.get("node_type") or a.get("type")
    bt = b.get("node_type") or b.get("type")
    if at != bt:
        return True
    ac = a.get("config") if isinstance(a.get("config"), dict) else {}
    bc = b.get("config") if isinstance(b.get("config"), dict) else {}
    if set(ac.keys()) != set(bc.keys()):
        return True
    for key in ac:
        if json.dumps(ac.get(key), sort_keys=True, default=str) != json.dumps(
            bc.get(key), sort_keys=True, default=str
        ):
            return True
    # Surface label / placement / event_trigger as changes when present.
    for field in ("label", "placement", "event_trigger"):
        if json.dumps(a.get(field), sort_keys=True, default=str) != json.dumps(
            b.get(field), sort_keys=True, default=str
        ):
            return True
    return False


def diff_graphs(
    base: dict[str, Any] | None,
    proposed: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare two GraphIR dicts at node/edge level.

    Returns ``{nodes_added, nodes_removed, nodes_changed, edges_changed}``
    where list fields hold ids / edge key strings for human-readable UI.
    Count fields mirror list lengths for compact summaries.
    """
    base_nodes = _node_map(base)
    prop_nodes = _node_map(proposed)

    added_ids = sorted(set(prop_nodes) - set(base_nodes))
    removed_ids = sorted(set(base_nodes) - set(prop_nodes))
    changed: list[dict[str, Any]] = []
    for nid in sorted(set(base_nodes) & set(prop_nodes)):
        if _node_changed(base_nodes[nid], prop_nodes[nid]):
            before = base_nodes[nid]
            after = prop_nodes[nid]
            changed.append(
                {
                    "id": nid,
                    "node_type": after.get("node_type") or after.get("type"),
                    "config_keys_before": sorted(_config_keys(before)),
                    "config_keys_after": sorted(_config_keys(after)),
                }
            )

    base_edges = _edge_set(base)
    prop_edges = _edge_set(proposed)
    edges_added = sorted(prop_edges - base_edges)
    edges_removed = sorted(base_edges - prop_edges)

    def _fmt_edge(e: tuple[str, str, str, str, str | None]) -> str:
        src_id, src_port, dst_id, dst_port, cond = e
        base_s = f"{src_id}:{src_port}->{dst_id}:{dst_port}"
        return f"{base_s}?{cond}" if cond else base_s

    return {
        "nodes_added": added_ids,
        "nodes_removed": removed_ids,
        "nodes_changed": changed,
        "edges_changed": {
            "added": [_fmt_edge(e) for e in edges_added],
            "removed": [_fmt_edge(e) for e in edges_removed],
        },
        "counts": {
            "nodes_added": len(added_ids),
            "nodes_removed": len(removed_ids),
            "nodes_changed": len(changed),
            "edges_added": len(edges_added),
            "edges_removed": len(edges_removed),
        },
    }


def _proposal_path(proposal_id: str, base_dir: str | Path | None = None) -> Path:
    safe = "".join(c for c in proposal_id if c.isalnum() or c in "-_")
    if not safe or safe != proposal_id:
        raise ValueError(f"Invalid proposal id: {proposal_id!r}")
    return proposals_dir(base_dir) / f"{safe}.json"


def _read_proposal(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("proposals: corrupt file %s (%s)", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _write_proposal(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _public_summary(proposal: dict[str, Any]) -> dict[str, Any]:
    """List-friendly view without the full proposed_graph payload."""
    diff = proposal.get("diff_summary") or {}
    counts = diff.get("counts") if isinstance(diff, dict) else None
    return {
        "id": proposal.get("id"),
        "status": proposal.get("status"),
        "created_at": proposal.get("created_at"),
        "updated_at": proposal.get("updated_at"),
        "actor": proposal.get("actor"),
        "summary": proposal.get("summary"),
        "base_graph_hash": proposal.get("base_graph_hash"),
        "diff_summary": {
            "nodes_added": (counts or {}).get("nodes_added", len(diff.get("nodes_added") or [])),
            "nodes_removed": (counts or {}).get("nodes_removed", len(diff.get("nodes_removed") or [])),
            "nodes_changed": (counts or {}).get("nodes_changed", len(diff.get("nodes_changed") or [])),
            "edges_changed": (
                (counts or {}).get("edges_added", 0) + (counts or {}).get("edges_removed", 0)
                if counts
                else (
                    len((diff.get("edges_changed") or {}).get("added") or [])
                    + len((diff.get("edges_changed") or {}).get("removed") or [])
                )
            ),
        },
    }


def create_proposal(
    graph_dict: dict[str, Any],
    summary: str,
    actor: str = "agent",
    *,
    base_graph: dict[str, Any] | None = None,
    base_graph_hash: str | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Persist a pending proposal and return it. Records audit ``proposal.create``."""
    if not isinstance(graph_dict, dict) or not graph_dict:
        raise ValueError("graph must be a non-empty GraphIR dict")
    summary_s = (summary or "").strip() or "Graph change proposal"
    actor_s = (actor or "agent").strip() or "agent"
    proposal_id = uuid.uuid4().hex[:12]

    resolved_base_hash = base_graph_hash
    if resolved_base_hash is None and base_graph is not None:
        resolved_base_hash = _graph_hash(base_graph)

    diff = diff_graphs(base_graph, graph_dict)
    now = _utc_now()
    proposal: dict[str, Any] = {
        "id": proposal_id,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "actor": actor_s,
        "summary": summary_s,
        "base_graph_hash": resolved_base_hash,
        "proposed_graph": graph_dict,
        "diff_summary": diff,
    }

    path = _proposal_path(proposal_id, base_dir)
    with _lock:
        _write_proposal(path, proposal)

    try:
        from app.core.audit import record_audit

        record_audit(
            actor=actor_s,
            action="proposal.create",
            resource_type="proposal",
            resource_id=proposal_id,
            meta={
                "summary": summary_s,
                "counts": diff.get("counts"),
                "base_graph_hash": resolved_base_hash,
            },
            base_dir=base_dir,
        )
    except Exception as exc:
        logger.warning("proposals: audit create failed: %s", exc)

    return proposal


def list_proposals(
    status: str | None = None,
    *,
    base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return proposal summaries newest-first, optionally filtered by status."""
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
    root = proposals_dir(base_dir)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        data = _read_proposal(path)
        if not data:
            continue
        if status and data.get("status") != status:
            continue
        items.append(_public_summary(data))
    items.sort(key=lambda p: str(p.get("created_at") or ""), reverse=True)
    return items


def get_proposal(
    proposal_id: str,
    *,
    base_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return the full proposal document or None."""
    try:
        path = _proposal_path(proposal_id, base_dir)
    except ValueError:
        return None
    return _read_proposal(path)


def accept_proposal(
    proposal_id: str,
    *,
    actor: str = "human",
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Mark proposal accepted, audit, and return it (client loads ``proposed_graph``)."""
    path = _proposal_path(proposal_id, base_dir)
    with _lock:
        data = _read_proposal(path)
        if data is None:
            raise KeyError(f"Proposal not found: {proposal_id}")
        if data.get("status") != "pending":
            raise ValueError(f"Proposal is not pending (status={data.get('status')})")
        data["status"] = "accepted"
        data["updated_at"] = _utc_now()
        data["resolved_by"] = (actor or "human").strip() or "human"
        _write_proposal(path, data)

    try:
        from app.core.audit import record_audit

        record_audit(
            actor=(actor or "human").strip() or "human",
            action="proposal.accept",
            resource_type="proposal",
            resource_id=proposal_id,
            meta={"summary": data.get("summary"), "proposed_by": data.get("actor")},
            base_dir=base_dir,
        )
    except Exception as exc:
        logger.warning("proposals: audit accept failed: %s", exc)

    return data


def reject_proposal(
    proposal_id: str,
    *,
    actor: str = "human",
    reason: str | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Mark proposal rejected and record audit."""
    path = _proposal_path(proposal_id, base_dir)
    with _lock:
        data = _read_proposal(path)
        if data is None:
            raise KeyError(f"Proposal not found: {proposal_id}")
        if data.get("status") != "pending":
            raise ValueError(f"Proposal is not pending (status={data.get('status')})")
        data["status"] = "rejected"
        data["updated_at"] = _utc_now()
        data["resolved_by"] = (actor or "human").strip() or "human"
        if reason:
            data["reject_reason"] = str(reason)[:500]
        _write_proposal(path, data)

    try:
        from app.core.audit import record_audit

        record_audit(
            actor=(actor or "human").strip() or "human",
            action="proposal.reject",
            resource_type="proposal",
            resource_id=proposal_id,
            meta={
                "summary": data.get("summary"),
                "proposed_by": data.get("actor"),
                "reason": reason,
            },
            base_dir=base_dir,
        )
    except Exception as exc:
        logger.warning("proposals: audit reject failed: %s", exc)

    return data
